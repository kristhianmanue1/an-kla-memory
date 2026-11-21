# ADR-0074: La suite no tumba la máquina: procesos con dueño, freno por carga y una sola corrida

- **Estado:** Aceptada por delegación del orquestador (mandato 18, plan aprobado), 2026-11-20, tras r1 `fix-and-retry` (2 BLOCKER, 3 HIGH, 2 MEDIUM), r2 `fix-and-retry` (2 HIGH, 1 MEDIUM, 1 LOW) y r3 `proceed` (2 LOW) de otra familia (Gemini). Todo incorporado
- **Implementación:** No iniciada
- **Fecha:** 2026-11-20
- **Decide sobre:** cómo lanzan procesos las pruebas, cómo se detiene una corrida que dispara la carga, cuántas veces corre la suite completa por `ci_local`, y cómo se crean los repositorios de prueba.
- **Origen:** mandato 18 del orquestador (plan aprobado); medición `c74` y su análisis (informe 25 del capitán).

## Contexto

La máquina se comparte con otros capitanes, y el 2026-11-20 la suite de an-kla llegó a cargas de 371 y 600. Se midieron cuatro cosas:

1. **`ci_local --simulate-ci` corre la suite completa cinco veces.** La primera vez la corre de nivel superior. Las otras cuatro, anidadas en `tests/test_sealed_matrix_rows.py`, fila 15:
   - un `discover` con el venv;
   - un `discover` con `/usr/bin/python3` (3.9);
   - y `test_ci_local_both_modes`, que corre `ci_local` normal y `--simulate-ci`.
2. **Una corrida arranca unos 7 750 procesos.** Unos 6 250 son de `git` y 934 de `python -m an_kla`. De los de `git`, sólo unos 980 los lanza `make_project` (`init` y `commit`). El resto sale de **`identity_c0`**: 2–4 órdenes de `git` (`remote get-url`, `rev-parse`, `symbolic-ref`) cada vez que se construye la identidad del escritor, en las llamadas en proceso de las pruebas (r1, R74-03).
3. **Procesos sin dueño.** De los 34 sitios de `tests/` que lanzan procesos (`Popen` o `multiprocessing`), sólo dos matan por grupo. `test_remember_concurrency` escribe el archivo de parada de su `drain_loop` sólo si todo va bien, así que un fallo o un plazo agotado lo dejan lanzando `python -m an_kla inbox drain` cada 10 ms, sin fin. Además, su carpeta de registros queda fuera del temporal.
4. **La cascada de la medición `c74`.** El guion medidor llamaba a `main()` sin la guarda `if __name__ == "__main__":`. Cada hijo de `multiprocessing` con `spawn` volvía a importarlo y volvía a correr el `discover` entero: 33 corridas encadenadas. No fue la suite, pero la suite no tenía nada que lo frenara.

La regla de la máquina (carga por debajo de 6 antes de arrancar) no protege nada **durante** la corrida.

## Decisión

### 1. Quién es dueño de qué: una sesión por corrida, un grupo por hijo (r1, R74-01 y R74-02)

- **La sesión de la corrida.** `ci_local` lanza el `discover` con `start_new_session=True`, y su `pid` es el `sid` de la corrida. **`ci_local` queda fuera de esa sesión.** Así, matar la sesión no lo mata a él (rc 143), y puede leer el motivo y salir con rc 75. Tampoco toca la terminal del usuario.
- **El ayudante de las pruebas,** `tests/proc_support.py`, con `spawn(argv, **kw)` y `run(argv, timeout, **kw)`:
  - lanza cada hijo en **un grupo nuevo dentro de la misma sesión**: `process_group=0` en 3.11+, y `preexec_fn=os.setpgrp` en 3.9. **Nunca con `start_new_session`**: el hijo sigue en la sesión de la corrida, y el vigilante lo alcanza;
  - registra el grupo en la prueba, con `addCleanup` o con un gestor de contexto;
  - al fallar, al agotar el plazo, al interrumpirse y al acabar la prueba hace `killpg(SIGTERM)`, espera 5 s, hace `killpg(SIGKILL)` y recoge al hijo. Nunca queda un zombi;
  - `run` con plazo mata el **grupo**: `subprocess.run` mata sólo al hijo directo.
- **Se aplica a los 34 sitios** de `tests/` que lanzan procesos. `multiprocessing.Process` sigue en la sesión por defecto y se mata con `terminate`, `join(5)` y `kill` en un `finally`.
- **`drain_loop`** (`tests/remember_conc_worker.py`) tiene plazo propio: sale si `STOP` no aparece en un plazo dado por argumento, o si el proyecto desaparece. `test_remember_concurrency` escribe `STOP` en un `finally` y sus registros viven **dentro** del `TemporaryDirectory`.
- **Cómo se encuentran los procesos de una corrida,** tanto el vigilante (§2) como la comprobación final:
  - **todos los procesos de la sesión** de la corrida (`pgrep -s <sid>`);
  - **más todos los descendientes** del `pid` del `discover`, por el árbol de `ppid`. Este árbol recoge los que se hayan ido a otra sesión: el propio código de an-kla lanza el adaptador de custodio y el resolutor con `start_new_session=True` (ADR-0071 §3).
  - Se recorre otra vez hasta que no quede nadie.
- **Cómo se matan** (r2, R74-08). Si se mata en orden arbitrario, un padre muerto antes que su hijo deja a ese hijo reparentado a PID 1, fuera del árbol. Además, `killpg(sid)` no alcanza a los grupos con su propio `pgid`. Por eso se mata en este orden:
  1. se toma una **foto** de todos los procesos de la corrida (sesión más árbol), y se guardan sus `pid`, sus `pgid` y sus `sid`;
  2. **`SIGSTOP` a todos los de la foto**. Un proceso parado no termina ni crea hijos, así que nadie se reparenta mientras tanto;
  3. `killpg(SIGTERM)` a **cada `pgid`** distinto de la foto, `kill(SIGTERM)` a cada `pid`, y `SIGCONT` a todos para que la señal se entregue;
  4. se esperan 10 s;
  5. se vuelve a buscar: la sesión, el árbol, y además **todo proceso cuyo `sid` o `pgid` esté entre los guardados en la foto**. Esto recoge a los reparentados a PID 1. A lo que quede, `SIGKILL`.

  La comprobación final usa la misma búsqueda. Un proceso que termina por sí solo entre la foto y la señal da `ProcessLookupError`: se ignora, porque ya no está, que es lo que se buscaba (r3, R74-12).
  - **Límite declarado:** un proceso que crea su propia sesión **y además** se queda huérfano (su padre muere) se pierde en el árbol. En el código de an-kla eso sólo le puede pasar al adaptador o al resolutor, y an-kla los mata por grupo cuando vence su plazo (ADR-0071 §3).
- **Comprobación al final:** si al acabar el `discover` queda algún proceso de la corrida, el paso falla con `children_left`, lista sus `pid` y su orden (sin argumentos con datos) y los mata. Que quede alguno es un fallo.
- **Prueba:** una prueba que provoca un fallo a mitad de un `spawn` del ayudante comprueba que no queda nadie de su grupo.

### 2. Freno por carga: un vigilante en un proceso aparte

- **Qué es:** `scripts/load_guard.py`, un **proceso aparte**, no un hilo, para que pueda matar aunque el proceso principal esté atascado.
  - **Un vigilante por paso pesado** (r2, R74-09). `ci_local` corre cada paso que lanza procesos (el `discover`, el `kill -9` de la bandeja y, con `--matrix`, el 3.9) con un mismo `run_step()`. Esa función lanza el paso en su propia sesión, arranca un vigilante para esa sesión y, cuando el paso termina, **mata al vigilante y lo recoge** antes de pasar al siguiente. Ningún vigilante sobrevive a su paso, y ningún paso pesado corre sin vigilante.
  - El vigilante corre en la sesión de `ci_local`, no en la del paso. Lo mismo vale para todo guion de medición.
  - Recibe el `sid` y el `pid` del paso.
- **Cada cuánto mira:** `os.getloadavg()` cada 5 s.
- **Cuándo actúa:** si la carga a 1 minuto supera el umbral en **seis muestras seguidas** (30 s sostenidos, r1 R74-04).
  - Manda `SIGTERM` a todos los procesos de la corrida (§1), espera 10 s, manda `SIGKILL` a lo que quede y deja un archivo de motivo con las muestras.
  - Un pico pasajero ajeno a la prueba no basta.
- **El umbral:** por defecto **30**, cambiable con `AN_KLA_CI_LOAD_ABORT`. La máquina tiene 8 núcleos: 30 son casi 4 por núcleo, y por encima las pruebas de plazos ya fallan solas.
- **El archivo de motivo** se escribe de forma atómica: en un temporal, con `fsync` y `rename`. `ci_local` nunca lee uno a medias (r3, R74-13).
- **El resultado:** `ci_local`, que sigue vivo (§1), lee el archivo de motivo y sale con **rc 75, «abortada por carga»**, distinto de fallo (rc 1). Imprime las muestras y lo que se mató.
- **Su ciclo de vida:**
  - comprueba en cada muestra que su padre sigue vivo, y muere si `ci_local` muere;
  - nunca sobrevive a la corrida;
  - nunca mata nada fuera de los procesos de la corrida (§1).
- **Guiones de medición:** todo guion que corra la suite, o una parte grande de ella, vive en el repo (`scripts/`) o usa el ayudante y el vigilante, y lleva la guarda de `main`. **Prueba:** una prueba pequeña lanza un guion con `multiprocessing` en `spawn` y comprueba que el hijo **no** vuelve a lanzar la corrida (cuenta una marca en un archivo).

### 3. Una sola corrida completa por `ci_local`

| Corrida | Qué se hace |
|---|---|
| `discover` de nivel superior | Se queda: es la suite |
| Fila 15, con el venv | **Fuera.** Es la misma suite con el mismo intérprete |
| Fila 15, con Python 3.9 (`/usr/bin/python3`) | **A `ci_local --matrix`.** El 3.9 es un intérprete soportado y no hay otra corrida que lo pruebe. Es una orden aparte que se corre a propósito, en secuencia, con el freno, y **entra en los pasos del Operador de cada release** |
| `test_ci_local_both_modes` (normal y `--simulate-ci`) | **Fuera.** Los modos sólo cambian `GITHUB_ACTIONS`/`CI`, y su lógica ya la prueban `tests/test_ci_local_*` |

- La fila 15 deja de lanzar suites. **Se queda en la corrida normal el sondeo dirigido de `tests.test_sealed_bundle` con `/usr/bin/python3`** (r1, R74-05). Es un solo módulo, de pocos segundos, y es lo único que comprueba la cripto sellada en un host cuyo venv no la tiene. Se queda con su misma condición de hoy.
- **El paso de matriz de `ci_local`** (la sección `paso_matriz`) sólo corre con `--matrix`. Toma el 3.9 de `/usr/bin/python3` si existe y su versión es 3.9. Sin `--matrix`, escribe `SKIP (usa --matrix)`.
- **El `kill -9` de la bandeja** sigue como paso propio de `ci_local`, dentro del freno.

### 4. Los arranques de `git`: primero se mide de dónde salen (r1, R74-03)

- **Medir antes de cambiar.** `scripts/measure_suite.py` (§6) apunta cada arranque de `git` con la función que lo pide, sacada de la pila: `make_project`, `identity_c0.repo_id_for`, `branch_for`, `anchors_git` y otras. Con esa tabla se decide.
- **Plantilla de repositorio para `make_project`** (unos 980 arranques):
  - una plantilla por proceso de prueba, creada una vez (`git init`, la configuración y el commit base), comprobada sin archivos `.lock`;
  - se protege con una **huella**, no con permisos (r2, R74-10): al crearla se guarda el sha256 de su árbol, y antes de cada copia se comprueba. Si no coincide, se regenera. No se le quitan permisos de escritura, porque `copytree` los copiaría y Git no podría escribir en la copia;
  - cada prueba la copia con `shutil.copytree`, sin lanzar ningún proceso y sin copiar los `.lock`;
  - antes se comprueba, y se pone en el informe, que ninguna prueba depende de un `repo.id`, un commit o un `origin` distinto en cada proyecto;
  - el `repo.id` local depende de la ruta, así que sigue siendo distinto en cada copia.
- **`identity_c0`** (unos 5 000 arranques). **Se hace** (r2, R74-11), salvo que la medición de la pila muestre que esos arranques no vienen de ahí. Es una caché **dentro del proceso** de `repo_id_for` y `branch_for`:
  - la clave es la ruta real del checkout y el `mtime` de `.git/config` y `.git/HEAD`. Un cambio de remoto o de rama la invalida;
  - beneficia también al uso real (el servidor MCP construye la identidad muchas veces);
  - es un cambio de código de producto: entra con su propia prueba (cambiar el remoto o la rama invalida la caché). Si resulta delicado, no se hace y se dice.

### 5. `python -m an_kla` en proceso, sólo donde sea barato

- **Dónde:** en los módulos que sólo usan el resultado de una orden (el JSON de stdout y el rc), un ayudante `cli_in_process(argv, env, cwd)` llama a `an_kla.__main__.main(argv)`, con la salida capturada, el entorno y el `cwd` aislados, y `SystemExit` traducido a rc.
- **Lo que no cambia:** lo que prueba la CLI como proceso (señales, `kill -9`, candados entre procesos, el entorno heredado, MCP, la receta documentada y la batería) se queda como está.
- **Si no sale barato,** no se hace. Si un módulo depende de estado global que no se aísla con facilidad, se queda con el proceso, y se dice.

### 6. Medir antes y después

- **El guion:** `scripts/measure_suite.py`, en el repo, con la guarda, el ayudante y el vigilante. Da los arranques por tipo (clasificados por `argv[0]`, no por `-m`), los tiempos por módulo y el pico de carga.
- **El «antes» no se vuelve a correr** (r1, R74-06). Repetir la suite sin arreglar, con sus cinco corridas anidadas, puede tumbar otra vez la máquina. La línea base son:
  - los **recuentos** de `c74/medicion-antes.json`, que valen como los de un `discover` completo;
  - las **duraciones** de las corridas de `ci_local` que ya están registradas en esta carpeta.
- **El «después»** se mide con `scripts/measure_suite.py`, con el freno puesto, en la primera corrida completa con el arreglo. Se avisa antes al orquestador, que la vigila.

## Por qué no

- **Vigilante en un hilo:** un proceso principal atascado en una llamada que no suelta el GIL, o colgado esperando a un hijo, no lo dejaría actuar. Siendo un proceso aparte, mata la sesión pase lo que pase.
- **Bajar el paralelismo de las pruebas de concurrencia:** cambiaría lo que prueban. El freno y la muerte por grupo atajan la carga sin tocarlas.
- **Dejar el 3.9 en la corrida normal:** duplica la suite en cada `ci_local` para un intérprete que se usa poco. Al pasarlo a `--matrix` en los pasos de release, se sigue probando antes de publicar.
- **Reescribir las pruebas para no usar `git`:** muchas prueban precisamente cosas de Git (anclas, ramas, `HEAD`). La plantilla quita el coste sin cambiar lo que prueban.

## Consecuencias

- **Positivas:**
  - una sola corrida completa;
  - ningún proceso sobrevive a su prueba;
  - una corrida que dispara la carga se para sola, con un código propio;
  - muchos menos arranques de `git`.
- **Negativas:** el 3.9 ya no se prueba en cada `ci_local`, sólo con `--matrix`. Habrá que acordarse en cada release, y por eso entra en los pasos del Operador.
- **Neutras:** rc 75 es nuevo; quien lea el resultado de `ci_local` tiene que conocerlo.

## Pruebas de aceptación

1. **Muerte por grupo:** una prueba hace fallar un `spawn` a mitad, con un nieto vivo. Al acabar no queda nadie del grupo. Y un hijo del ayudante sigue en la sesión de la corrida: su `sid` es el de la corrida.
2. **`drain_loop`:** sin `STOP`, termina por su plazo, y termina también si el proyecto desaparece. `test_remember_concurrency` deja todo limpio aunque un cliente falle (con un fallo inyectado).
3. **Hijos vivos al final:** con un hijo que se escapa a propósito, `ci_local` da `children_left` y lo mata.
4. **Freno:**
   - con un umbral bajo y una carga simulada (el vigilante acepta una fuente de carga inyectable para la prueba), aborta con rc 75, mata la sesión y deja el motivo;
   - lo hace también con el proceso principal **atascado** (un `sleep` sin salida);
   - `ci_local` **sobrevive** y sale con rc 75: no está en la sesión que se mata;
   - alcanza a un nieto que se fue a otra sesión mientras su padre siga vivo, por el árbol de `ppid`;
   - un pico de menos de 30 s no aborta;
   - con un padre muerto antes que su hijo en otra sesión, el hijo reparentado a PID 1 se encuentra por su `sid` o su `pgid` guardados y se mata (R74-08);
   - el vigilante de un paso ya no existe cuando empieza el siguiente, y el paso `kill -9` tiene el suyo (R74-09);
   - y el vigilante muere si muere su padre.
5. **Guarda de `main`:** un hijo `spawn` no vuelve a lanzar la corrida.
6. **Una corrida:**
   - `ci_local --simulate-ci` lanza un solo `discover` completo (se cuenta);
   - `--matrix` lanza el del 3.9.
7. **Plantilla y caché:**
   - los mismos resultados que antes en los módulos que la usan, y menos arranques de `git`, medidos;
   - una copia de la plantilla es escribible, y una plantilla tocada se regenera (R74-10);
   - cambiar el remoto o la rama invalida la caché de `identity_c0`.
8. **La suite da los mismos resultados:** mismo número de pruebas y ninguna prueba que deje de pasar, salvo las de la fila 15 que salen de la corrida normal. El «después» se mide con `scripts/measure_suite.py` y se compara con los recuentos de `c74`.
9. **El sondeo sellado con 3.9** sigue en la corrida normal, en las mismas condiciones que hoy.

## Referencias

Mandato 18 del orquestador; informe 25 del capitán; `c74/informe-medir-c74.md`; ADR-0063 (criterio 3, `kill -9`).
