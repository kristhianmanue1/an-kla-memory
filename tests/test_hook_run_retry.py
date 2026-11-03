"""Deterministic explicit-run retries, rejection and durability regressions."""
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from an_kla import hook_runs, store_locks
from an_kla.attest import ensure_attest_files
from an_kla.custody import CustodyError
from an_kla.store import MemoryStore


def mint(root, **overrides):
    args = dict(hook_id="before-task", trigger="before_task", action="retrieve",
                exit_code=0, subject={"kind": "query", "query": "x"}, run_id="retry")
    args.update(overrides)
    return hook_runs.mint_hook_run(MemoryStore(root), **args)


def worker(root, barrier, queue, query):
    barrier.wait(timeout=20)
    try:
        queue.put(("ok", mint(root, subject={"kind": "query", "query": query})))
    except Exception as exc:
        queue.put(("error", str(exc)))


def _craft_entry(store, run_id, now, *, adapter_fingerprint=None,
                 project_uuid=None, store_identity=None):
    """Fabrica una entrada válida firmada con la llave de la bóveda de
    prueba (para duplicados históricos, binding ajeno y sobre-medidos)."""
    import hashlib
    import hmac as hmac_module
    from an_kla.attest import SIGNATURE_PREFIX, _load_key
    from an_kla.canonical import canonical_json, digest_bytes, digest_json
    from an_kla.identity import read_binding

    binding = read_binding(store)
    entry = dict(
        schema=hook_runs.RUNS_SCHEMA, run_id=run_id,
        hook_id='before-task', trigger='before_task', action='retrieve',
        exit_code=0, subject_digest=digest_json({'kind': 'query', 'query': 'x'}),
        project_uuid=project_uuid or binding['store']['project_uuid'],
        store_identity=store_identity or binding['store_identity'],
        adapter_fingerprint=adapter_fingerprint, observed_at=now,
    )
    key = _load_key(store)
    entry['run_hmac'] = SIGNATURE_PREFIX + hmac_module.new(
        key, canonical_json(entry), hashlib.sha256).hexdigest()
    raw = canonical_json(entry) + b'\n'
    return raw, digest_bytes(raw)[7:] + '.json'


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()
        ensure_attest_files(self.root)
        self.directory = hook_runs._runs_dir(self.store)

    def test_clock_and_restart_preserve_bytes(self):
        original = mint(self.root, now="2026-01-01T00:00:00Z")
        path = next(self.directory.glob('*.json'))
        raw = path.read_bytes()
        self.assertEqual(mint(self.root, now="2026-11-02T00:00:00Z"), original)
        self.assertEqual(path.read_bytes(), raw)
        ctx = multiprocessing.get_context('spawn')
        barrier, queue = ctx.Barrier(1), ctx.Queue()
        process = ctx.Process(target=worker, args=(self.root, barrier, queue, 'x'))
        process.start(); process.join(20)
        if process.is_alive():
            process.terminate(); process.join()
            self.fail('child timed out')
        self.assertEqual(queue.get(timeout=2), ('ok', original))
        queue.close(); queue.join_thread()
        self.assertEqual(path.read_bytes(), raw)

    def test_conflicting_fields_do_not_write(self):
        mint(self.root)
        fields = dict(hook_id='other', trigger='material_close_or_handoff',
                      action='checkpoint', exit_code=1, subject={'other': 1},
                      adapter_fingerprint='changed')
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        for key, value in fields.items():
            with self.subTest(key=key), self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_conflict'):
                mint(self.root, **{key: value})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})
        mint(self.root, run_id='different')
        self.assertEqual(len(list(self.directory.iterdir())), 2)

    def test_concurrent_same_and_different_payload(self):
        for queries in [('x','x'), ('a','b')]:
            with self.subTest(queries=queries):
                for p in self.directory.glob('*.json'): p.unlink()
                ctx = multiprocessing.get_context('spawn')
                barrier, queue = ctx.Barrier(2), ctx.Queue()
                processes = [ctx.Process(target=worker, args=(self.root, barrier, queue, q)) for q in queries]
                try:
                    for p in processes: p.start()
                    for p in processes: p.join(20)
                    self.assertFalse(any(p.is_alive() for p in processes))
                    results = [queue.get(timeout=2) for _ in processes]
                    self.assertEqual(len(list(self.directory.glob('*.json'))), 1)
                    if queries[0] == queries[1]: self.assertEqual(results[0], results[1])
                    else: self.assertIn(('error','hook_run_conflict'), results)
                finally:
                    for p in processes:
                        if p.is_alive(): p.terminate(); p.join()
                    queue.close(); queue.join_thread()

    def test_corrupt_and_nonregular_candidates(self):
        self.directory.mkdir(parents=True)
        path = self.directory / ('a'*64 + '.json')
        for kind in ['json', 'fifo', 'symlink', 'directory', 'large']:
            with self.subTest(kind=kind):
                if kind == 'fifo': os.mkfifo(path)
                elif kind == 'symlink': path.symlink_to(self.root / 'missing')
                elif kind == 'directory': path.mkdir()
                else: path.write_bytes(b'x' * (65537 if kind == 'large' else 1))
                with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
                    mint(self.root)
                if kind == 'directory': path.rmdir()
                else: path.unlink()

    def test_scan_limit_and_positive_control(self):
        mint(self.root)
        with patch.object(hook_runs, '_MAX_ENTRIES_SCANNED', 1):
            self.assertEqual(mint(self.root), mint(self.root))
            (self.directory / 'z.json').write_text('{}')
            with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_scan_limit'):
                mint(self.root)

    def test_lock_timeout(self):
        with self.store.write_lock(), patch.object(store_locks, 'WRITE_LOCK_DEADLINE_SECONDS', 0):
            with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_lock_busy'):
                mint(self.root)
        self.assertFalse(self.directory.exists())

    def test_retry_after_fsync_failure(self):
        # Actual publication writes complete bytes before injected file fsync.
        with patch('an_kla.attest.os.fsync', side_effect=OSError('private path')):
            with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_publication_uncertain'):
                mint(self.root)
        files = list(self.directory.glob('*.json'))
        self.assertEqual(len(files), 1)
        before = files[0].read_bytes()
        result = mint(self.root)
        self.assertEqual(result['digest'], 'sha256:' + files[0].stem)
        self.assertEqual(before, files[0].read_bytes())
        with patch.object(hook_runs, '_fsync_dir', side_effect=OSError('private path')):
            with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_publication_uncertain'):
                mint(self.root)
        self.assertEqual(before, files[0].read_bytes())

    def test_input_rejected_before_effects(self):
        for kwargs in [dict(exit_code=256), dict(run_id=''), dict(run_id=[]),
                       dict(subject=[]), dict(now='bad'), dict(adapter_fingerprint=4)]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_invalid_input'):
                mint(self.root, **kwargs)
        self.assertFalse(self.directory.exists())

    def test_missing_flags_fail_closed(self):
        # Delta de locks 2026-11-02: disponibilidad verificada ANTES de
        # abrir candidatos o publicar (sin fallback cero); el código es
        # hook_run_platform_unsupported y el camino B no publica nada.
        for flag in ('O_NOFOLLOW', 'O_NONBLOCK'):
            saved = getattr(hook_runs.os, flag)
            delattr(hook_runs.os, flag)
            try:
                with self.subTest(flag=flag), self.assertRaisesRegex(
                        hook_runs.HookRunError, 'hook_run_platform_unsupported'):
                    mint(self.root)
            finally:
                setattr(hook_runs.os, flag, saved)
        self.assertFalse(self.directory.exists())

    def test_flags_absent_empty_dir_publishes_nothing(self):
        for flag in ('O_NOFOLLOW', 'O_NONBLOCK'):
            saved = getattr(hook_runs.os, flag)
            delattr(hook_runs.os, flag)
            try:
                with self.assertRaisesRegex(
                        hook_runs.HookRunError, 'hook_run_platform_unsupported'):
                    mint(self.root)
            finally:
                setattr(hook_runs.os, flag, saved)
        self.assertFalse(self.directory.exists())


    def test_root_as_file_fails_closed(self):
        self.directory.mkdir(parents=True)
        self.directory.rmdir()
        self.directory.write_text('no soy directorio')
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root)
        self.assertTrue(self.directory.is_file())

    def test_root_symlink_fails_closed(self):
        outside = self.root / 'runs-outside'
        outside.mkdir()
        self.directory.parent.mkdir(parents=True)
        self.directory.symlink_to(outside)
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_ancestor_symlink_fails_closed(self):
        outside = self.root / 'runs-outside'
        outside.mkdir()
        hook_runs_dir = self.root / '.an-kla' / 'hook-runs'
        hook_runs_dir.mkdir()
        (hook_runs_dir / 'runs').symlink_to(outside)
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_foreign_binding_entry_fails_closed(self):
        self.directory.mkdir(parents=True)
        raw, name = _craft_entry(
            self.store, 'foreign', '2026-01-01T00:00:00Z',
            project_uuid='00000000-0000-0000-0000-000000000000',
            store_identity='sha256:' + 'b' * 64)
        (self.directory / name).write_bytes(raw)
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root, run_id='foreign')
        self.assertEqual(len(list(self.directory.glob('*.json'))), 1)

    def test_renamed_entry_fails_closed(self):
        mint(self.root)
        path = next(self.directory.glob('*.json'))
        path.rename(self.directory / ('f' * 64 + '.json'))
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root)

    def test_oversized_signed_entry_fails_closed(self):
        self.directory.mkdir(parents=True)
        raw, name = _craft_entry(
            self.store, 'big', '2026-01-01T00:00:00Z',
            adapter_fingerprint='x' * (hook_runs._MAX_ENTRY_BYTES + 1))
        (self.directory / name).write_bytes(raw)
        with self.assertRaisesRegex(hook_runs.HookRunError, 'hook_run_evidence_invalid'):
            mint(self.root, run_id='big')

    def test_duplicate_evidence_fails_closed(self):
        self.directory.mkdir(parents=True)
        for now in ('2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z'):
            raw, name = _craft_entry(self.store, 'duplicated', now)
            (self.directory / name).write_bytes(raw)
        with self.assertRaisesRegex(
                hook_runs.HookRunError, 'hook_run_duplicate_evidence'):
            mint(self.root, run_id='duplicated')

    def test_scan_incomplete_on_scandir_error(self):
        self.directory.mkdir(parents=True)
        with patch.object(hook_runs.os, 'scandir', side_effect=OSError('boom')):
            with self.assertRaisesRegex(
                    hook_runs.HookRunError, 'hook_run_scan_incomplete'):
                mint(self.root)

    def test_memory_vault_removed_before_lock_fails_without_recreation(self):
        # Delta de locks, caso de refutación 1: `memory/` desaparece entre
        # el preflight y el lock -> fallo sin recrear layout ni publicar.
        import shutil
        calls = {'n': 0}
        real = hook_runs.check_custody

        def sabotage(store, *, binding):
            calls['n'] += 1
            result = real(store, binding=binding)
            if calls['n'] == 1:
                shutil.rmtree(self.root / '.an-kla' / 'memory')
            return result

        with patch.object(hook_runs, 'check_custody', side_effect=sabotage):
            with self.assertRaises(FileNotFoundError):
                mint(self.root)
        self.assertFalse((self.root / '.an-kla' / 'memory').exists())
        self.assertFalse(self.directory.exists())

    def test_custody_changed_while_waiting_publishes_nothing(self):
        # Delta de locks, caso de refutación 2 (proxy determinista): la
        # revalidación bajo lock detecta custodia cambiada -> cero escrituras.
        from an_kla.custody import CustodyError
        mint(self.root)
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        calls = {'n': 0}
        real = hook_runs.check_custody

        def diverges_on_revalidation(store, *, binding):
            calls['n'] += 1
            if calls['n'] >= 2:
                raise CustodyError('store_root_divergence')
            return real(store, binding=binding)

        with patch.object(hook_runs, 'check_custody',
                          side_effect=diverges_on_revalidation):
            with self.assertRaisesRegex(CustodyError, 'store_root_divergence'):
                mint(self.root)
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_path_b_disowned_vault_raises_custody_and_writes_nothing(self):
        other_project = self.root / 'other-project'
        other_project.mkdir()
        foreign = self.root / 'foreign'
        wrong = MemoryStore(other_project, store_root=foreign)
        wrong.initialize()
        ensure_attest_files(other_project, store=wrong)
        with self.assertRaisesRegex(CustodyError, 'store_root_divergence'):
            hook_runs.mint_hook_run(
                MemoryStore(self.root, store_root=foreign),
                hook_id='before-task', trigger='before_task',
                action='retrieve', exit_code=0,
                subject={'kind': 'query', 'query': 'x'}, run_id='disowned')
        self.assertFalse((foreign / 'hook-runs').exists())

    def test_external_custody_alias_shares_universe(self):
        vault_project = self.root / 'alias-project'
        vault_project.mkdir()
        vault = self.root / 'alias-vault'
        store = MemoryStore(vault_project, store_root=vault)
        store.initialize()
        ensure_attest_files(vault_project, store=store)
        args = dict(hook_id='before-task', trigger='before_task',
                    action='retrieve', exit_code=0,
                    subject={'kind': 'query', 'query': 'x'}, run_id='retry')
        first = hook_runs.mint_hook_run(store, **args)
        second = hook_runs.mint_hook_run(
            MemoryStore(vault_project, store_root=vault), **args)
        self.assertEqual(first, second)
        self.assertEqual(
            len(list(hook_runs._runs_dir(store).glob('*.json'))), 1)

    def test_scan_limit_with_real_files_and_target_beyond_threshold(self):
        original = mint(self.root)
        for index in range(2000):
            raw, name = _craft_entry(self.store, f'filler-{index}',
                                     '2026-01-01T00:00:00Z')
            (self.directory / name).write_bytes(raw)
        with self.assertRaisesRegex(
                hook_runs.HookRunError, 'hook_run_scan_limit'):
            mint(self.root)
        self.assertEqual(len(list(self.directory.glob('*.json'))), 2001)
        # Control positivo: dentro del umbral el escaneo procede y devuelve
        # el original (el run buscado está dentro del universo verificado).
        filler = next(p for p in self.directory.glob('*.json')
                      if json.loads(p.read_bytes())['run_id'] != 'retry')
        filler.unlink()
        self.assertEqual(mint(self.root), original)
        self.assertEqual(len(list(self.directory.glob('*.json'))), 2000)

    def test_durability_opens_verified_entry_once(self):
        # Pin de regresión TOCTOU: en el reintento, `_restore_durability`
        # verifica y fsync sobre UN solo descriptor; el total por retry es
        # dos aperturas del .json (lectura de escaneo + durabilidad). Una
        # regresión que reabra tras verificar mostraría tres.
        mint(self.root)
        path = next(self.directory.glob('*.json'))
        opened = []
        real = hook_runs.os.open

        def counting_open(target, *args, **kwargs):
            opened.append(str(target))
            return real(target, *args, **kwargs)

        with patch.object(hook_runs.os, 'open', side_effect=counting_open):
            self.assertEqual(mint(self.root)['digest'], 'sha256:' + path.stem)
        json_opens = [name for name in opened if name.endswith('.json')]
        self.assertEqual(json_opens, [str(path)] * 2)


if __name__ == '__main__': unittest.main()