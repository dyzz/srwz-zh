import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import build_release
import build_release_chd

class ChdPolicyTests(unittest.TestCase):
    def test_hook_failure_blocks_packaging_even_with_no_roundtrip(self):
        config={'schema_version':5,'editions':{e:{'target_iso':{'path':f'{e}.iso'}} for e in ('best','sp')}}
        with patch.object(build_release_chd,'resolve_chdman',return_value='chdman'), \
             patch.object(build_release_chd,'load_config',return_value=config), \
             patch.object(build_release,'verify_dual_config_bindings') as bindings, \
             patch.object(build_release,'verify_built_in_skip',side_effect=ValueError('missing skip')) as hook, \
             patch.object(build_release_chd,'build_edition') as encode:
            self.assertEqual(build_release_chd.main(['--config','release.json','--no-verify']),1)
            bindings.assert_called_once_with(config);hook.assert_called_once();encode.assert_not_called()

    def test_both_clis_require_explicit_release(self):
        with self.assertRaises(SystemExit) as error:
            build_release_chd.main([])
        self.assertEqual(error.exception.code,2)
        with patch.object(sys,'argv',['build_release.py']),self.assertRaises(SystemExit) as error:
            build_release.parse_args()
        self.assertEqual(error.exception.code,2)
