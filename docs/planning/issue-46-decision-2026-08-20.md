# Decisión — #46: export sellado (2026-08-20)

Punto 10 del plan `plan-backlog-2026-08-20.md`. Documento de decisión;
**sin código**. Resultado esperado: `escalate`.

## Lo que el issue ya resuelve bien (validado)

El diseño del issue (adaptador externo wrap/unwrap por stdio con CEK
opaca; AEAD por entrada con nonce derivado por HKDF del índice; AAD =
registro canónico del manifiesto; `manifest_mac` HMAC sobre `core`;
`verify` sin clave devolviendo `structure_verified/payloads_verified`
separados; `content_sha256` siempre sobre el plano para compatibilidad
con `compaction-restore-proof-v1`; no-reproducibilidad declarada) es
arquitectónicamente sólido y consistente con la frontera del proyecto:
AN-KLA no acuña, deriva ni almacena material de clave — mismo patrón
que la autoridad privilegiada de write/refute. Nada de eso se replica
aquí; se da por bueno como base del ADR futuro.

> **NOTA DE SUPERSESIÓN (2026-08-20, registro posterior)**: la frase
> anterior describía la **premisa vigente antes de elegir la opción B**
> y quedó **superseda por ADR-0042** al aceptarse esa opción. Bajo B,
> el core **genera una CEK efímera** (os.urandom) y **deriva subclaves**
> (aead_key/bundle_id/mac_key) en memoria de proceso. Lo que permanece
> **exclusivamente externo** es la **custodia de la capacidad de
> wrap/unwrap** (KEK, clave privada, passphrase, Keychain, KMS): ese
> material jamás entra al core, y el core **no persiste clave alguna en
> disco de forma intencional** (persisten `wrapped_cek` —único artefacto
> destinado a recuperar la CEK— y los derivados no-secretos
> `bundle_id`/`manifest_mac`; swap, hibernación, crash dumps y copias
> del runtime quedan fuera de la garantía: ver ADR-0042 §1/§Límites). El registro histórico se conserva
> intacto; esta nota es la vigente.
>
> **También supersede el mecanismo de nonce descrito arriba** ("AEAD por
> entrada con nonce derivado por HKDF del índice"): ADR-0042 lo
> reemplazó por un **contador puro** `i.to_bytes(12,"big")` — la
> derivación HKDF truncada a 96 bits no era inyectiva entre índices
> (hallazgo F1 del maintainer). La mención de HKDF en el párrafo
> resumido del issue #46 es histórica y no normativa.

## Threat model (mini)

**Atacante**: quien obtiene lectura del bundle en su destino (disco
externo, carpeta sincronizada, otra máquina) sin la clave. **Fuera de
modelo**: el operador legítimo con clave, el endpoint con la clave
(atención: el adaptador la custodia), y la destrucción/borrado. Hoy el
bundle viaja en claro y la única defensa son permisos POSIX del origen
que no viajan: confidencialidad en reposo = cero. La autenticidad
también es cero: quien reescribe el bundle entero recalcula los hashes
y `verify` pasa (hueco que ADR-0027 declara). El sello ataca exactamente
esos dos ejes.

## La decisión que el diseño no puede tomar solo: dónde vive la crypto

`pyproject.toml` declara **cero dependencias Python de runtime**
(verificado; `jsonschema` es extra de test; el export actual es 100%
stdlib). El AEAD propuesto **no existe en la stdlib** — y tampoco HKDF
(la derivación de nonce/MAC a mano sería más "crypto casera"). Salidas:

| Opción | Costo | Riesgo |
|---|---|---|
| A. dependencia dura | rompe la promesa de despliegue sin deps; amplía supply-chain a TODO usuario | inaceptable sin orden explícita |
| B. extra opcional `[sealed]` (p.ej. `cryptography` para AES-256-GCM) + fail-closed `sealed_extra_not_installed` | default limpio; el que selle paga la dependencia; `pip install "an-kla-memory[sealed] @ git+…@tag"` verificado funcional | dos perfiles de instalación; la crypto entra al core (más TCB del core, pero invariantes del issue — nonce por construcción, AAD por entrada, MAC del manifiesto — **testeables en core**) |
| C. crypto propia en stdlib | re-implementar AEAD/HKDF a mano | inaceptable: no se escribe criptografía casera |
| D. **delegación total al adaptador**: el core no ve CEK ni ciphertext por entrada; empaqueta el stream y el adaptador devuelve UN blob opaco | **cero dependencias**; core sin crypto | cada adaptador reimplementa AEAD/AAD/nonce (TCB por adaptador); las invariantes §2-§3 del issue dejan de ser testeables en core; el `manifest_mac` exige otra vuelta de tuerca (el adaptador debería firmar); contrato de adaptador mayor; un adaptador flojo degrada el sello sin que el core lo detecte |

**B y D son las únicas vivas.** Elegir entre ellas es política, no
técnica: B concentra el riesgo criptográfico en una librería auditada y
mantiene las garantías verificables en core, al precio de una
dependencia opt-in; D mantiene el core puro al precio de mover la
corrección criptográfica a cada adaptador, sin pruebas en core que la
exijan. **Recomendación de trabajo: B**, con fail-closed en ambos
bordes (`sealing_adapter_required`, `sealed_extra_not_installed` —
nunca degradar a claro).

Precisión verificada: `cryptography` (46.x) no expone XChaCha20
(nonce 24 B) — sólo ChaCha20-Poly1305 con 12 B y AESGCM; XChaCha
existe en PyNaCl/libsodium **sólo vía bindings de bajo nivel**
(`crypto_aead_xchacha20poly1305_ietf_*`, sin clase AEAD). El algoritmo
concreto lo decide el ADR futuro con esa realidad.

## Otras decisiones que el ADR futuro debe cerrar (lista de entrada)

1. Algoritmo concreto (AES-256-GCM en `cryptography` es el candidato
   viable sin bindings; ver precisión arriba).
2. Versión del schema: `export-manifest-v1` evoluciona aditivamente
   (`seal`, `manifest_mac`, `wrapped_cek`, `adapter_id`) o `-v2`.
3. Política del export v1 en claro: soportado para siempre o
   deprecación anunciada (los bundles existentes deben seguir
   restaurables).
4. La fuga residual que el issue manda declarar (§7): tamaños y conteos
   del plano visibles pese al cifrado por entrada.
5. Ronda adversarial **pre-code** con revisión orientada a cripto
   (nonce-reuse por construcción, downgrade claro↔sellado, swap de
   `adapter_id`, downgrade de verify v2→v1).
6. `backup` no es un subcomando propio: comparte superficie con
   `export` (`__main__.py:251`) y queda cubierto por el mismo ADR.
7. Sin librería no hay HKDF en stdlib: si se rechaza B, la derivación
   de nonce/MAC de D también es "crypto casera" — nombrarlo en el ADR.

## Escalate

Este punto no puede avanzar sin el maintainer:

- **¿B (extra `[sealed]`, crypto auditada en core, garantías testeables)
  o D (adaptador total, core puro, corrección criptográfica fuera de
  pruebas del core)?** Es política de riesgo, no técnica.
- **¿Autorizar el ADR de sealed-export/v1 (siguiente número libre)** con la base del issue,
  la opción elegida y su ronda adversarial pre-code con foco cripto?

Mientras tanto, el estado actual es honesto y declarado: capabilities
expone `plaintext: true` en export y cada resultado de export/verify
lleva el warning `plaintext_export_contains_untrusted_memory_data`;
ADR-0027 dice textualmente "hashes dan integridad accidental, no
autenticidad ni confidencialidad". Ningún consumidor es engañado hoy.

## Frontera de confianza

El sellado protege confidencialidad en reposo del bundle; no convierte
la memoria restaurada en confiable (`untrusted_memory_data` sigue
siendo true tras `restore`), no autentica al operador y no sustituye
permisos del filesystem en el store vivo.
