import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import io
import contextlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('engine', ROOT / 'sd_import.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)

class ImportTests(unittest.TestCase):
    def setUp(self):
        e.RESULT.update(copied=0,duplicates=0,deleted=0,failed=0)
        e.GUI = False
        self.tmp = tempfile.TemporaryDirectory(prefix='carddock-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'card'
        self.dest = self.root / 'library'
        self.source.mkdir()

    def media(self, name='DCIM/100CAM/IMG_0001.JPG', data=b'first original', timestamp=1700000000):
        p = self.source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (timestamp, timestamp))
        return p

    def run_import(self, *args, answers='', success=True):
        run = subprocess.run([sys.executable, str(ROOT/'sd_import.py'), '--source',str(self.source),'--dest',str(self.dest),'--gui',*args], input=answers,capture_output=True,text=True)
        if success:
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        return run

    def copies(self):
        return [p for p in self.dest.rglob('*') if p.is_file() and '.carddock' not in p.parts]

    def result(self, run):
        return json.loads(next(l[7:] for l in run.stdout.splitlines() if l.startswith('##DONE ')))

    def test_same_name_same_day_preserves_both_originals(self):
        self.media(data=b'first')
        self.media('DCIM/101CAM/IMG_0001.JPG',b'second')
        r=self.run_import()
        self.assertEqual({p.read_bytes() for p in self.copies()},{b'first',b'second'})
        self.assertEqual(self.result(r)['copied'],2)

    def test_case_insensitive_collision_is_reserved(self):
        self.media('DCIM/A/IMG.JPG',b'one')
        self.media('DCIM/B/img.jpg',b'two')
        self.run_import()
        self.assertEqual(len(self.copies()),2)
        self.assertEqual(len({p.name.casefold() for p in self.copies()}),2)

    def test_preview_creates_no_destination(self):
        self.media()
        r=self.run_import('--dry-run')
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.result(r)['planned'],1)

    def test_preview_preserves_unrelated_partial_and_database(self):
        self.media(); self.run_import()
        partial=self.dest/'2023-11-14'/'unrelated.part'; partial.write_bytes(b'keep')
        before={str(p):p.read_bytes() for p in self.dest.rglob('*') if p.is_file()}
        self.run_import('--dry-run')
        after={str(p):p.read_bytes() for p in self.dest.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_changed_bytes_same_name_size_timestamp_are_imported(self):
        p=self.media(data=b'AAAA'); self.run_import()
        p.write_bytes(b'BBBB'); os.utime(p,(1700000000,1700000000))
        r=self.run_import()
        self.assertEqual(self.result(r)['copied'],1)
        self.assertEqual({p.read_bytes() for p in self.copies()},{b'AAAA',b'BBBB'})

    def test_duplicate_checks_both_copies(self):
        self.media(); self.run_import()
        r=self.run_import()
        self.assertEqual(self.result(r)['duplicates'],1)
        self.assertEqual(self.result(r)['copied'],0)

    def test_missing_destination_is_reimported(self):
        self.media(); self.run_import(); self.copies()[0].unlink()
        r=self.run_import()
        self.assertEqual(self.result(r)['copied'],1)

    def test_corrupt_destination_is_kept_and_new_copy_created(self):
        p=self.media(data=b'AAAA'); self.run_import()
        self.copies()[0].write_bytes(b'XXXX')
        self.run_import()
        self.assertEqual({p.read_bytes() for p in self.copies()},{b'AAAA',b'XXXX'})
        self.assertTrue(p.exists())

    def test_defaults_keep_originals(self):
        p=self.media(); self.run_import(); self.assertTrue(p.exists())

    def test_deletion_requires_second_confirmation(self):
        p=self.media(); self.run_import('--ask-delete',answers='1\nNO\n'); self.assertTrue(p.exists())

    def test_verified_deletion_only_after_confirmation(self):
        p=self.media(); r=self.run_import('--ask-delete',answers='1\nDELETE\n')
        self.assertFalse(p.exists()); self.assertEqual(self.result(r)['deleted'],1)
        self.assertEqual(self.copies()[0].read_bytes(),b'first original')

    def test_previous_imports_not_deleted_by_default(self):
        p=self.media(); self.run_import(); self.run_import('--ask-delete',answers='1\nDELETE\n')
        self.assertTrue(p.exists())

    def test_previous_imports_explicit_scope(self):
        p=self.media(); self.run_import(); self.run_import('--ask-delete','--scope','all',answers='1\nDELETE\n')
        self.assertFalse(p.exists())

    def test_changed_source_blocks_deletion(self):
        p=self.media(data=b'AAAA'); self.run_import(); snap=e.identity(p); sha=e.digest(p)
        p.write_bytes(b'BBBB')
        with self.assertRaises(ValueError): e.delete_verified(p,self.copies()[0],sha,snap)
        self.assertTrue(p.exists())

    def test_changed_destination_blocks_deletion(self):
        p=self.media(data=b'AAAA'); self.run_import(); snap=e.identity(p); sha=e.digest(p)
        target=self.copies()[0]; target.write_bytes(b'BBBB')
        with self.assertRaises(ValueError): e.delete_verified(p,target,sha,snap)
        self.assertTrue(p.exists())

    def test_commit_never_overwrites_existing_destination(self):
        a=self.root/'part'; b=self.root/'final'; a.write_bytes(b'A'); b.write_bytes(b'B')
        with self.assertRaises(FileExistsError): e.commit_exclusive(a,b)
        self.assertEqual(b.read_bytes(),b'B'); self.assertEqual(a.read_bytes(),b'A')

    def test_failed_verification_cleans_only_owned_temporary_file(self):
        p=self.media(); target=self.root/'output'/'IMG.JPG'; target.parent.mkdir()
        unrelated=target.parent/'unrelated.part'; unrelated.write_bytes(b'keep')
        with self.assertRaises(ValueError): e.verified_copy(p,target,'wrong')
        self.assertEqual(list(target.parent.iterdir()),[unrelated])

    def test_source_destination_overlap_rejected_before_writes(self):
        self.media(); dest=self.source/'output'
        with self.assertRaises(ValueError): e.paths(self.source,dest)
        self.assertFalse(dest.exists())
        with self.assertRaises(ValueError): e.paths(self.source,self.root)

    def test_symlink_source_file_skipped(self):
        actual=self.root/'real.JPG'; actual.write_bytes(b'private')
        (self.source/'linked.JPG').symlink_to(actual)
        r=self.run_import(); self.assertEqual(self.result(r)['copied'],0)

    def test_symlink_destination_date_folder_rejected(self):
        self.media(); self.dest.mkdir(); outside=self.root/'elsewhere'; outside.mkdir()
        (self.dest/'2023-11-14').symlink_to(outside,target_is_directory=True)
        r=self.run_import(success=False); self.assertNotEqual(r.returncode,0); self.assertEqual(list(outside.iterdir()),[])

    def test_unknown_files_remain_on_card(self):
        p=self.media('DCIM/data.unknown',b'unknown'); self.run_import('--ask-delete',answers='1\nDELETE\n')
        self.assertTrue(p.exists()); self.assertEqual(self.copies(),[])

    def test_nested_layout_shoot_and_companions(self):
        self.media(); self.media('DCIM/100CAM/IMG_0001.XMP',b'companion')
        self.run_import('--layout','nested','--shoot','Beach')
        self.assertEqual(len(list((self.dest/'2023/11/14 Beach').glob('*'))),2)

    def test_photos_filter_leaves_video(self):
        self.media(); video=self.media('DCIM/100CAM/CLIP.MOV',b'video')
        self.run_import('--kind','photos')
        self.assertEqual(len(self.copies()),1); self.assertTrue(video.exists())

    def test_invalid_shoot_cannot_escape_destination(self):
        self.media(); r=self.run_import('--shoot','../../escape',success=False)
        self.assertNotEqual(r.returncode,0); self.assertFalse(self.dest.exists())

    def test_low_disk_space_prevents_copy(self):
        self.media()
        args=e.argparse.Namespace(source=str(self.source),dest=str(self.dest),shoot='',dry_run=False,kind='all',layout='daily',verify='thorough',ask_delete=False,scope='run',eject=False)
        with patch.object(e.shutil,'disk_usage',return_value=e.shutil._ntuple_diskusage(1,1,0)):
            with self.assertRaisesRegex(ValueError,'space'): e.run(args)
        self.assertEqual(self.copies(),[])

    def test_locked_file_is_not_unlocked_for_deletion(self):
        if not hasattr(os,'chflags'): self.skipTest('macOS flags')
        p=self.media(); self.run_import(); os.chflags(p, e.stat.UF_IMMUTABLE)
        try:
            with self.assertRaisesRegex(ValueError,'protected'): e.delete_verified(p,self.copies()[0],e.digest(p),e.identity(p))
            self.assertTrue(p.exists())
        finally: os.chflags(p,0)

    def test_identical_companion_contents_keep_distinct_names(self):
        self.media('DCIM/IMG_1.JPG',b'image one')
        self.media('DCIM/IMG_1.XMP',b'same settings')
        self.run_import()
        self.media('DCIM/IMG_2.JPG',b'image two')
        self.media('DCIM/IMG_2.XMP',b'same settings')
        self.run_import()
        self.assertEqual(len(self.copies()),4)

    def test_symlink_history_is_rejected(self):
        self.media(); self.dest.mkdir()
        meta=self.dest/'.carddock'; meta.mkdir()
        outside=self.root/'outside.sqlite'; outside.write_bytes(b'keep')
        (meta/'imports.sqlite3').symlink_to(outside)
        self.run_import(success=False)
        self.assertEqual(outside.read_bytes(),b'keep')

    def test_unmounted_destination_not_created(self):
        self.media()
        with self.assertRaisesRegex(ValueError,'disconnected'):
            e.paths(self.source,Path('/Volumes/CardDock-not-mounted-test/Photos'))

    def test_corrupt_history_stops_without_deleting_source(self):
        p=self.media(); meta=self.dest/'.carddock'; meta.mkdir(parents=True)
        (meta/'imports.sqlite3').write_bytes(b'invalid sqlite database')
        run=self.run_import('--ask-delete',answers='1\nDELETE\n',success=False)
        self.assertNotEqual(run.returncode,0); self.assertTrue(p.exists())

    def test_stop_reports_deletions_already_completed(self):
        self.media('DCIM/A.JPG',b'first'); self.media('DCIM/B.JPG',b'second')
        args=e.argparse.Namespace(source=str(self.source),dest=str(self.dest),shoot='',dry_run=False,kind='all',layout='daily',verify='thorough',ask_delete=True,scope='run',eject=False,gui=False)
        original=e.delete_verified
        calls=[]
        def interrupt_second(*args):
            if calls: raise KeyboardInterrupt()
            original(*args); calls.append(True)
        output=io.StringIO()
        with patch.object(e,'parse_args',return_value=args),patch.object(e,'confirm',side_effect=['1','DELETE']),patch.object(e,'delete_verified',side_effect=interrupt_second),contextlib.redirect_stdout(output):
            rc=e.main()
        self.assertEqual(rc,130)
        self.assertIn('1 originals already deleted',output.getvalue())
        self.assertEqual(len(list((self.source/'DCIM').glob('*.JPG'))),1)

    def test_large_file_streamed_byte_for_byte(self):
        data=b'original bytes\0'*(1024*1024)
        self.media(data=data); self.run_import()
        self.assertEqual(self.copies()[0].read_bytes(),data)

if __name__ == '__main__': unittest.main()
