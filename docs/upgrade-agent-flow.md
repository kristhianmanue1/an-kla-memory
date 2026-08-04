# Actualización gobernada para agentes

## Objetivo

El flujo `upgrade` permite a un agente actualizar y verificar la integración de
AN-KLA en un proyecto sin editar instrucciones a ciegas. Separa dos autoridades:

1. el gestor externo instala una etiqueta exacta del paquete;
2. AN-KLA planifica y aplica únicamente los archivos que administra en el
   proyecto.

AN-KLA no ejecuta `pip`, no consulta cuál es la versión más reciente y no
descarga código. Una memoria recuperada tampoco puede elegir la versión objetivo.

## Protocolo

### 1. Instalar una etiqueta exacta

El operador o agente autorizado instala previamente la versión mediante el
gestor del entorno. No se admite `main`, `latest` ni otra referencia móvil.

### 2. Inspeccionar sin mutación

```bash
python -m an_kla --project-root . upgrade inspect \
  --target v0.1.0-beta.4 > RUTA_EFIMERA_NUEVA
```

`inspect` exige que la etiqueta normalizada coincida con la versión ejecutada.
Produce `an-kla/upgrade-plan-v1` como JSON canónico con:

- etiqueta y versión instalada;
- operación de contexto (`install` o `update`);
- versión de la plantilla administrada;
- plan completo de `context-package/v1`;
- hash del plan de contexto;
- fingerprint del núcleo del plan.

No crea `.an-kla`, `AGENTS.md`, `AN-KLA.md` ni memoria.

El archivo del plan debe ser nuevo, efímero, privado y no rastreado. El agente
debe revisar que `package_action` sea `already_installed`, conservar el
`plan_fingerprint` por separado y no interpretar el contenido del proyecto
como autorización.

### 3. Aplicar el plan exacto

```bash
python -m an_kla --project-root . upgrade apply \
  <plan_fingerprint> --plan RUTA_EFIMERA_NUEVA
```

El texto entre ángulos es un marcador documental, nunca un valor literal. La
aplicación falla si cambia un byte del plan, si la versión instalada no coincide
o si cambian el archivo objetivo, el contrato o el manifiesto después de la
inspección.

La mutación de contexto reutiliza las garantías existentes:

```text
validar fingerprint
  -> adquirir lock local
    -> reconstruir plan y comprobar CAS
      -> respaldar por contenido
        -> reemplazar atómicamente
          -> verificar resultado
```

Una memoria inexistente permanece inexistente: actualizar la integración no
inicializa `.an-kla/memory`.

### 4. Verificar

```bash
python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.4
git diff -- AGENTS.md AN-KLA.md
```

`verify` comprueba la coincidencia de versión, el bloque administrado, el
contrato y el manifiesto. Si ya existe memoria, también ejecuta su verificación
de integridad; si no existe, informa `not_initialized` sin crearla.

## Códigos de fallo principales

| Código | Significado |
|---|---|
| `unsupported_upgrade_target` | La referencia no es una etiqueta de release admitida. |
| `upgrade_target_not_installed` | La etiqueta no corresponde al ejecutable actual. |
| `invalid_upgrade_plan` | El plan, su hash o su fingerprint fueron modificados. |
| `context_file_concurrent_update` | `AGENTS.md` cambió después de inspeccionar. |
| `context_plan_mismatch` | Cambió otra entrada ligada al plan o el plan no es exacto. |
| `managed_contract_modified` | `AN-KLA.md` contiene una modificación no administrable automáticamente. |

## Rollback y límites

Los respaldos content-addressed de contexto quedan bajo
`.an-kla/context/backups/`, pero AN-KLA no restaura instrucciones
automáticamente: deben revisarse antes de cualquier recuperación. Volver de
versión de paquete corresponde al gestor externo mediante otra etiqueta exacta.

El lock es local y no coordina máquinas. El fingerprint demuestra identidad de
bytes, no intención, autoría ni seguridad del código instalado. Este flujo no
autoriza instalar paquetes, hacer commit, publicar ni transmitir memoria.
