# Desarrollo con Python en macOS

## Versiones y propósito

AN-KLA Memory requiere Python 3.9 o posterior. Para separar desarrollo de
compatibilidad se usan dos intérpretes:

- Python 3.12 es el entorno local recomendado y vive en `.venv/`;
- Python 3.9 es el mínimo soportado y se conserva como una comprobación de
  compatibilidad, además de la matriz de CI.

La carpeta `.venv/` es local, regenerable y está ignorada por Git. Nunca debe
incluirse en un commit ni copiarse a otra máquina: cada equipo la crea de nuevo
con su propio intérprete.

## 1. Comprobar el entorno existente

Desde la raíz del repositorio:

```bash
test -x .venv/bin/python && .venv/bin/python --version
.venv/bin/python -c 'import sys; print(sys.executable); print(sys.version)'
```

Si muestra Python 3.12, el entorno ya puede usarse. Para agentes y procesos no
interactivos se prefiere la ruta explícita `.venv/bin/python`; así no dependen
de que una shell haya ejecutado `activate`.

El entorno verificado durante el desarrollo de esta alfa usa Python 3.12.12.
Ese número describe el entorno observado, no eleva el requisito del paquete:
`pyproject.toml` sigue declarando `requires-python = ">=3.9"`.

## 2. Localizar Python 3.12

```bash
command -v python3.12
python3.12 --version
```

En una Mac con Apple Silicon e instalación de Homebrew suele resolverse como
`/opt/homebrew/bin/python3.12`. En una Mac Intel puede estar bajo
`/usr/local/bin`. No se debe fijar ninguna de esas rutas en scripts del
proyecto; `command -v` permite usar la instalación real de cada máquina.

Si `python3.12` no existe, se puede instalar Python 3.12 mediante Homebrew:

```bash
brew install python@3.12
```

También es válido un instalador oficial de Python. Después de instalar, se
repite `command -v python3.12` antes de crear el entorno.

## 3. Crear el entorno virtual

Sólo cuando `.venv/bin/python` no exista:

```bash
python3.12 -m venv .venv
.venv/bin/python --version
```

AN-KLA no tiene dependencias de ejecución externas. Desde la raíz del
repositorio, el intérprete puede importar el paquete y ejecutar las pruebas sin
instalarlo en el entorno:

```bash
.venv/bin/python -c 'import an_kla; print(an_kla.VERSION)'
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Esto mantiene el arranque determinista y evita descargar paquetes. Una
instalación editable es opcional para trabajo de empaquetado:

```bash
.venv/bin/python -m pip install -e .
```

La instalación editable puede necesitar descargar las herramientas de
construcción declaradas en `pyproject.toml`; no es prerrequisito para la suite
normal.

## 4. Activación opcional

Una persona puede activar el entorno durante una sesión interactiva:

```bash
source .venv/bin/activate
python --version
```

Para salir:

```bash
deactivate
```

Los comandos documentados para automatización siguen usando
`.venv/bin/python` explícitamente para que su resultado no dependa del estado
de la shell.

## 5. Entorno incorrecto o dañado

Un entorno virtual no es portable entre rutas, versiones o máquinas. Si no
resuelve Python 3.12, se conserva temporalmente fuera del repositorio para
diagnóstico y se crea uno nuevo. Primero se comprueba que el destino elegido no
exista:

```bash
test ! -e ../an-kla-memory-venv-backup
mv .venv ../an-kla-memory-venv-backup
python3.12 -m venv .venv
.venv/bin/python --version
```

Una vez confirmado el entorno nuevo, el operador decide cuándo retirar la
copia. No se elimina automáticamente ni se guarda en Git.

## 6. Validación antes de proponer cambios

La comprobación principal usa Python 3.12:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Si `python3` corresponde al Python 3.9 del sistema, se valida además el mínimo
soportado:

```bash
python3 --version
python3 -m unittest discover -s tests -p 'test_*.py'
```

Antes de interpretar el resultado, siempre se registra la versión mostrada.
La CI vuelve a ejecutar la suite en Python 3.9 y 3.12 sobre Linux, macOS y
Windows; el entorno local complementa esa matriz, no la sustituye.

## Diagnóstico rápido

```bash
command -v python3.12
.venv/bin/python --version
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
git status --short
```

El último comando debe confirmar que `.venv/` no aparece como contenido por
versionar.
