"""Actual rendered DOM tests. Set AA_TEST_URL to a local Quarto preview."""
import json
import os
import unittest


@unittest.skipUnless(os.environ.get('AA_TEST_URL'), 'requires a local rendered site')
class BrowserSafetyTests(unittest.TestCase):
    def test_all_eight_pages_use_the_projected_data_without_runtime_errors(self):
        from playwright.sync_api import sync_playwright
        from pathlib import Path
        with sync_playwright() as p:
            local='/home/juke/.cache/ms-playwright/chromium-1217/chrome-linux/chrome'
            browser=p.chromium.launch(headless=True,executable_path=os.environ.get('AA_CHROMIUM',local if Path(local).exists() else p.chromium.executable_path),args=['--no-sandbox'])
            page=browser.new_page()
            selectors={'index':'#wp-budget svg','latent':'#umap-svg','network':'#cy canvas',
                       'lifecycle':'#lifecycle-scatter svg','drift':'#drift-table pre',
                       'pulse':'details.pulse-week','people':'#people-gate','about':'main'}
            for name,selector in selectors.items():
                with self.subTest(page=name):
                    errors=[]
                    def handler(e):errors.append(str(e))
                    page.on('pageerror',handler)
                    response=page.goto(os.environ['AA_TEST_URL']+'/'+name+'.html',wait_until='networkidle')
                    page.wait_for_selector(selector)
                    self.assertEqual(response.status,200)
                    self.assertEqual(errors,[])
                    page.remove_listener('pageerror',handler)
            page.goto(os.environ['AA_TEST_URL']+'/index.html',wait_until='networkidle')
            coverage=page.request.get(os.environ['AA_TEST_URL']+'/data/pub/taxonomy_coverage.json').json()
            self.assertEqual(int(page.locator('.kpi-tile .value').first.text_content()),coverage['n_commits'])
            browser.close()

    def test_latent_labels_and_tooltip_subject_are_inert(self):
        from playwright.sync_api import sync_playwright
        from pathlib import Path
        with sync_playwright() as p:
            local='/home/juke/.cache/ms-playwright/chromium-1217/chrome-linux/chrome'
            browser=p.chromium.launch(headless=True,executable_path=os.environ.get('AA_CHROMIUM',local if Path(local).exists() else p.chromium.executable_path),args=['--no-sandbox'])
            page=browser.new_page()
            payload='<img src="data:," onerror="window.__aaInjected=true">'
            topics={'topics':[{'topic_id':0,'label':payload,'top_words':[payload],'size':1,'color':'#0072B2'}]}
            rows=[{'org':'snuconnectome','repo':'visible','sha':'fixture','subject':payload}]
            points=[{'sha':'fixture','x':0,'y':0,'topic_id':0}]
            for name,data in [('topics',topics),('commits_slim',rows),('embeddings',points)]:
                page.route('**/data/pub/'+name+'.json',lambda route, request, data=data:route.fulfill(status=200,content_type='application/json',body=json.dumps(data)))
            page.goto(os.environ['AA_TEST_URL']+'/latent.html',wait_until='networkidle')
            page.wait_for_selector('#umap-svg circle')
            page.locator('#umap-svg circle').dispatch_event('mouseover')
            page.wait_for_timeout(200)
            self.assertFalse(page.evaluate('window.__aaInjected === true'))
            self.assertIn('<img',page.locator('#topic-table').text_content())
            self.assertIn('<img',page.locator('#umap-tooltip').text_content())
            browser.close()

    def test_internal_people_and_public_tables_treat_strings_as_text(self):
        from playwright.sync_api import sync_playwright
        from pathlib import Path
        payload='<img src=x onerror="window.__aaInjected=true">'
        fixtures={
            'people': ('people', [{'login':'fixture','display':payload,'repos':['org/'+payload],
                'domains':[payload],'last_activity':'2026-01-01','n_repos':1,'active_weeks':1,
                'days_since_pi_repo_commit':None,'recent_repo_counts':[1],'in_roster':False}], '.person-card'),
            'lifecycle': ('lifecycle', [{'repo':'org/'+payload,'org':'snuconnectome','domain':payload,
                'wp':payload,'archived':False,'idle_days':400,'contributors':1,'person_weeks':20,
                'commits':1,'succession_risk':True}], '#succession td'),
            'drift': ('drift', [{'repo':'org/'+payload,'commits':1,'suggested_domain':payload}], '#drift-table pre')}
        with sync_playwright() as p:
            local='/home/juke/.cache/ms-playwright/chromium-1217/chrome-linux/chrome'
            browser=p.chromium.launch(headless=True,executable_path=os.environ.get('AA_CHROMIUM',local if Path(local).exists() else p.chromium.executable_path),args=['--no-sandbox'])
            for name,(file,data,selector) in fixtures.items():
                with self.subTest(page=name):
                    page=browser.new_page();errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.route('**/data/pub/'+file+'.json',lambda route, request, data=data:route.fulfill(status=200,content_type='application/json',body=json.dumps(data)))
                    page.goto(os.environ['AA_TEST_URL']+'/'+name+'.html',wait_until='networkidle')
                    page.wait_for_selector(selector)
                    self.assertFalse(page.evaluate('window.__aaInjected === true'))
                    self.assertIn('<img',page.locator(selector).first.text_content())
                    self.assertEqual(errors,[])
                    page.close()
            browser.close()

    def test_pulse_text_is_inert(self):
        from playwright.sync_api import sync_playwright
        from pathlib import Path
        with sync_playwright() as p:
            local='/home/juke/.cache/ms-playwright/chromium-1217/chrome-linux/chrome'
            browser = p.chromium.launch(headless=True, executable_path=os.environ.get(
                'AA_CHROMIUM', local if Path(local).exists() else p.chromium.executable_path), args=['--no-sandbox'])
            page = browser.new_page()
            payload = [{'week_iso': '2026-W01', 'commit_count': 1, 'top_topics': [],
                        'delta_bullets': ['<img src="data:," onerror="window.__aaInjected=true">']}]
            page.route('**/data/pub/weekly_pulse.json', lambda route: route.fulfill(
                status=200, content_type='application/json', body=json.dumps(payload)))
            page.goto(os.environ['AA_TEST_URL'] + '/pulse.html', wait_until='networkidle')
            page.wait_for_selector('details.pulse-week li')
            self.assertFalse(page.evaluate('window.__aaInjected === true'))
            self.assertIn('<img', page.locator('details.pulse-week li').first.text_content())
            browser.close()


if __name__ == '__main__':
    unittest.main()
