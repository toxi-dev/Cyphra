"""Gecko160 native search schema and local collection integration (MPL-2.0)."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/desktop-search-160'
spec = importlib.util.spec_from_file_location('desktop_search_branding', ROOT / 'scripts/brand-engine.py')
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)

NODE_ROUTE = r'''
const assert = require('node:assert/strict'), vm = require('node:vm');
let input = ''; process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  try {
    const { source, selector, pref } = JSON.parse(input), calls = [];
    const settings = { get: async () => [{recordType:'engine',identifier:'brave'}],
      on() {}, db:{clear:async()=>{}} };
    const rust = { setSearchConfig: value => calls.push(['v2',JSON.parse(value)]),
      setSearchConfigV3: value => calls.push(['v3',JSON.parse(value)]),
      setConfigOverrides: value => calls.push(['overrides',JSON.parse(value)]) };
    const context = vm.createContext({ console, AppConstants:{platform:'linux'},
      Components:{ Constructor: function(){ return function(){}; } },
      ChromeUtils:{defineLazyGetter:(target,key,get)=>Object.defineProperty(target,key,{get})},
      XPCOMUtils:{defineLazyPreferenceGetter:(target,key,_pref,value)=>target[key]=value,
        declareLazy: definitions => 'configV3FeatureGate' in definitions
        ? {configV3FeatureGate:pref} : {
          RemoteSettings: key => {calls.push(['collection',key]);return settings;},
          SearchUtils:null, SearchEngineSelector:{init:()=>rust},
          logConsole:{debug(){},error(){}}
        }} });
    const clean = code => code.replace(/^import .*?;\r?\n/gm,'').replace(/^export /gm,'');
    vm.runInContext(clean(source), context, {timeout:1000});
    const actual = { gate:context.SearchUtils.configV3FeatureGate,
      key:context.SearchUtils.SETTINGS_KEY };
    // Run the unmodified upstream selector with the transformed native utility.
    const selectorContext = vm.createContext({console,AppConstants:{platform:'linux'},
      XPCOMUtils:{declareLazy:()=>({
        RemoteSettings:key=>{calls.push(['collection',key]);return settings;},
        SearchUtils:context.SearchUtils,SearchEngineSelector:{init:()=>rust},
        logConsole:{debug(){},error(){}}
      })} });
    vm.runInContext(clean(selector)+'\nthis.TestSelector=SearchEngineSelector;',selectorContext,{timeout:1000});
    await new selectorContext.TestSelector(()=>{}).getEngineConfiguration();
    actual.calls=calls; process.stdout.write(JSON.stringify(actual));
  } catch(error) { console.error(error);process.exitCode=1; }
});
'''


class DesktopSearchBrandingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (FIXTURE / 'SearchUtils.sys.mjs').read_text()
        cls.selector = (FIXTURE / 'SearchEngineSelector.sys.mjs').read_text()

    def route(self, source, pref):
        result = subprocess.run(['node', '-e', NODE_ROUTE],
            input=json.dumps({'source':source,'selector':self.selector,'pref':pref}),
            text=True, capture_output=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def test_upstream_control_reproduces_feature_selected_schema(self):
        for pref, key, method in [(False,'search-config-v2','v2'),(True,'search-config-v3','v3')]:
            actual = self.route(self.source, pref)
            self.assertEqual(actual['gate'],pref)
            self.assertEqual(actual['key'],key)
            self.assertIn(['collection',key],actual['calls'])
            self.assertTrue(any(call[0] == method for call in actual['calls']))

    def test_both_persisted_feature_choices_use_only_local_v2_and_empty_overrides(self):
        source = brand.local_search_utils(self.source)
        for pref in (False,True):
            actual = self.route(source,pref)
            self.assertIs(actual['gate'],False)
            self.assertEqual(actual['key'],'cyphra-search-config-v1')
            self.assertEqual(actual['calls'],[
                ['collection','cyphra-search-config-v1'],
                ['v2',{'data':[{'recordType':'engine','identifier':'brave'}]}],
                ['overrides',{'data':[]}],
            ])

    def test_unfamiliar_or_duplicate_schema_getters_are_refused(self):
        for changed in (
            self.source.replace('return lazy.configV3FeatureGate;','return true;',1),
            self.source.replace('"search-config-v3" : "search-config-v2"','"search-config-v4" : "search-config-v3"',1),
            self.source+'\nget configV3FeatureGate() { return lazy.configV3FeatureGate; }\n',
        ):
            with self.assertRaises(ValueError):
                brand.local_search_utils(changed)

    def test_other_search_utility_code_remains_identical(self):
        changed = brand.local_search_utils(self.source)
        pattern = r'get (?:configV3FeatureGate|SETTINGS_KEY)\(\)\s*\{[^}]*\}'
        self.assertEqual(re.sub(pattern,'REVIEWED_GETTER',self.source),
                         re.sub(pattern,'REVIEWED_GETTER',changed))


if __name__ == '__main__':
    unittest.main()
