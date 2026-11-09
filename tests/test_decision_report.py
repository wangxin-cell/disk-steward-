"""Decision reports render synthetic metadata only; no user paths are accessed."""

import copy
import html
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/disk-steward/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    import decision_report as report
finally:
    sys.path.pop(0)

GIB = 1024 ** 3
FILE = 'C:\\DecisionFixture\\Downloads\\archive.iso'
SECOND_FILE = 'C:\\DecisionFixture\\Documents\\notes.pdf'


def fixture_plan():
    def candidate(path, size, category):
        return {'path': path, 'logical_bytes': size, 'category': category, 'volume_id': 'volume-c',
                'action': 'review_for_archive_or_verified_copy', 'risk': 'needs_user_review',
                'hardlink_count': 1, 'evidence': ['Metadata-only synthetic fixture.'],
                'estimated_reclaimable_bytes': None}

    def directory(path, size, count):
        return {'path': path, 'volume_id': 'volume-c', 'category': 'user_file',
                'logical_bytes': size, 'observed_files': count, 'hardlinked_files': 0,
                'deduplicated_file_names': 0, 'incomplete': False, 'is_scan_root': False,
                'action': 'review_directory_contents_before_selecting_files',
                'estimated_reclaimable_bytes': None, 'evidence': ['Inclusive overlapping summary.']}

    return {
        'schema_version': 1, 'created_at': '2026-11-05T01:00:00+08:00',
        'scan_created_at': '2026-11-05T00:59:00+08:00', 'scan_incomplete': True,
        'goal_bytes': 20 * GIB, 'goal_kind': 'target_free_space',
        'goal_volume': {'volume_id': 'volume-c', 'path': 'C:\\',
                        'queried_at': 'C:\\DecisionFixture', 'scan_roots': ['C:\\DecisionFixture'],
                        'sampled_at': '2026-11-05T00:59:00+08:00',
                        'total_bytes': 100 * GIB, 'used_bytes': 95 * GIB, 'free_bytes': 5 * GIB},
        'baseline_free_bytes': 5 * GIB, 'required_additional_bytes': 15 * GIB,
        'capacity_snapshot_status': 'below_free_target',
        'goal_evaluation': 'unknown_until_user_choices_and_post_action_volume_measurement',
        'candidates': [candidate(FILE, 20 * GIB, 'archive_or_installer'),
                       candidate(SECOND_FILE, 2 * GIB, 'user_file')],
        'directory_reviews': [directory('C:\\DecisionFixture', 50 * GIB, 100),
                              directory('C:\\DecisionFixture\\Downloads', 30 * GIB, 60)],
        'candidate_logical_bytes': 22 * GIB, 'automatic_reclaimable_bytes': 0,
        'excluded_system_files': 1, 'excluded_other_or_unknown_volume_files': 0,
        'limitations': ['Synthetic bounded sample; no files were read or changed.'],
    }


def choice(path=FILE, action='copy_then_release', destination='volume-d'):
    result = {'path': path, 'action': action, 'explanation': 'User proposal for a synthetic example.',
              'consequence': 'Needs independent validation and later approval.'}
    if action == 'copy_then_release' and destination is not None:
        result['destination_volume_id'] = destination
    return result


def scenarios(*items):
    return {'schema_version': 1, 'scenarios': [{'name': 'conservative', 'choices': list(items)}]}


def visible_text(markdown):
    """Undo Markdown punctuation escapes only for literal-preservation checks."""
    return re.sub(r'\\([^\w\s])', r'\1', markdown)


class DecisionReportIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.decision-test-', dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.input = self.base / 'plan.json'
        self.input.write_text(json.dumps(fixture_plan()), encoding='utf-8')
        self.output = self.base / 'report.md'

    def test_duplicate_json_keys_rejected_instead_of_last_value_winning(self):
        self.input.write_text('{"schema_version":1,"schema_version":2}', encoding='utf-8')
        with self.assertRaises(ValueError):
            report.load_json(self.input)

    def test_nested_duplicate_json_keys_rejected(self):
        self.input.write_text('{"nested":{"path":"first","path":"second"}}', encoding='utf-8')
        with self.assertRaises(ValueError):
            report.load_json(self.input)

    def test_oversized_input_rejected_before_parsing(self):
        self.input.write_bytes(b' ' * 129)
        with self.assertRaises(ValueError):
            report.load_json(self.input, max_bytes=128)

    def test_existing_output_is_not_overwritten(self):
        self.output.write_text('existing valuable report', encoding='utf-8')
        with self.assertRaises((ValueError, OSError)):
            report.write_report(self.output, 'replacement')
        self.assertEqual(self.output.read_text(), 'existing valuable report')

    def test_write_is_utf8_and_does_not_create_source_paths(self):
        text = report.render_report(fixture_plan(), language='zh')
        report.write_report(self.output, text)
        self.assertEqual(self.output.read_text(encoding='utf-8'), text)
        self.assertRegex(text, '[\u4e00-\u9fff]')

    def test_cli_renders_both_languages_from_explicit_plan(self):
        for language in ('zh', 'en'):
            output = self.base / f'report-{language}.md'
            with self.subTest(language=language), patch('sys.stdout', new_callable=io.StringIO):
                code = report.main(['--plan', str(self.input), '--output', str(output), '--language', language])
            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())
            self.assertIn('archive', output.read_text(encoding='utf-8'))

    def test_cli_with_choices_is_only_a_report(self):
        choices = self.base / 'choices.json'
        choices.write_text(json.dumps(scenarios(choice())), encoding='utf-8')
        with patch('sys.stdout', new_callable=io.StringIO):
            code = report.main(['--plan', str(self.input), '--choices', str(choices),
                                '--output', str(self.output), '--language', 'en'])
        self.assertEqual(code, 0)
        self.assertTrue(self.output.is_file())
        self.assertEqual(sorted(item.name for item in self.base.iterdir()),
                         ['choices.json', 'plan.json', 'report.md'])

    def test_cli_rejects_duplicate_keys_without_creating_output(self):
        self.input.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
        with patch('sys.stderr', new_callable=io.StringIO):
            result = report.main(['--plan', str(self.input), '--output', str(self.output)])
        self.assertNotEqual(result, 0)
        self.assertFalse(self.output.exists())


class DecisionReportRenderingTests(unittest.TestCase):
    def test_rendering_never_opens_or_stats_referenced_files(self):
        plan = fixture_plan()
        with patch('builtins.open', side_effect=AssertionError('Report attempted file IO')), \
                patch.object(Path, 'open', side_effect=AssertionError('Report opened a path')), \
                patch.object(Path, 'stat', side_effect=AssertionError('Report statted a path')), \
                patch.object(Path, 'lstat', side_effect=AssertionError('Report lstatted a path')):
            rendered = report.render_report(plan, scenarios(choice()), language='en')
        self.assertTrue(rendered)
        self.assertEqual(plan, fixture_plan(), 'Rendering must not mutate the input plan')

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), language='unsupported')

    def test_incomplete_scan_is_visible_in_readable_report(self):
        text = report.render_report(fixture_plan(), language='en')
        self.assertRegex(text.lower(), r'incomplete|partial|omissions')
        self.assertIn('2026-11-05', visible_text(text))

    def test_duplicate_candidate_aliases_are_rejected(self):
        plan = fixture_plan()
        duplicate = copy.deepcopy(plan['candidates'][0])
        duplicate['path'] = 'c:/decisionfixture/downloads/ARCHIVE.ISO'
        plan['candidates'].append(duplicate)
        with self.assertRaises(ValueError):
            report.render_report(plan, language='en')

    def test_directory_summaries_cannot_be_chosen_as_files(self):
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(choice(path='C:\\DecisionFixture')), language='en')

    def test_unknown_choice_path_is_rejected(self):
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(choice(path='C:\\UnknownFixture\\missing.iso')), language='en')

    def test_duplicate_choice_path_aliases_are_rejected(self):
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(choice(), choice(path='c:/decisionfixture/downloads/ARCHIVE.ISO')), language='en')

    def test_explicit_keep_requires_reason_and_consequence(self):
        incomplete = {'path': FILE, 'action': 'keep'}
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(incomplete), language='en')

    def test_unknown_action_or_approval_field_is_not_accepted(self):
        unknown = choice(action='delete_now')
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(unknown), language='en')
        inputs = scenarios(choice())
        inputs['approved'] = True
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), inputs, language='en')

    def test_excessive_free_text_is_rejected(self):
        item = choice()
        item['explanation'] = 'x' * (report.MAX_TEXT + 1)
        with self.assertRaises(ValueError):
            report.render_report(fixture_plan(), scenarios(item), language='en')

    def test_hostile_explanations_are_literal_text_in_both_languages(self):
        attack = ('<img src=x onerror=alert(1)> [Open](https://evil.invalid) '
                  '![image](https://evil.invalid/a) | injected-cell\n'
                  '# INJECTED\n```powershell\nRemove-Item C:\\*\n```')
        item = choice()
        item.update(explanation=attack, consequence=attack)
        for language in ('zh', 'en'):
            with self.subTest(language=language):
                text = report.render_report(fixture_plan(), scenarios(item), language=language)
                self.assertIn('evil.invalid', visible_text(text), 'Proposed rationale should remain reviewable as literal text')
                self.assertNotIn('<img src=', text)
                self.assertNotIn('\n# INJECTED', text)
                self.assertNotIn('\n```powershell', text)
                self.assertNotRegex(text, r'(?<!\\)\]\(https://evil\.invalid')
                self.assertNotRegex(text, r'(?<!\\)\| injected-cell')

    def test_hostile_path_text_cannot_create_markdown_or_html(self):
        plan = fixture_plan()
        hostile = 'C:\\DecisionFixture\\[Run](https://evil.invalid) <script>bad()</script>\n# INJECTED'
        plan['candidates'][0]['path'] = hostile
        for language in ('zh', 'en'):
            with self.subTest(language=language):
                text = report.render_report(plan, language=language)
                self.assertNotIn('<script>', text)
                self.assertNotIn('\n# INJECTED', text)
                self.assertNotRegex(text, r'(?<!\\)\]\(https://evil\.invalid')

    def test_bare_uris_are_display_text_not_active_links(self):
        item = choice()
        item['explanation'] = 'https://evil.invalid file:///C:/Example/private.txt javascript:alert(1)'
        rendered = report.render_report(fixture_plan(), scenarios(item), language='en')
        for scheme in ('https://', 'file:///', 'javascript:'):
            self.assertNotIn(scheme, rendered)
        self.assertIn(item['explanation'], html.unescape(visible_text(rendered)))

    def test_bidi_and_control_characters_cannot_visually_hide_path_or_action(self):
        controls = ('\u061c\u200e\u200f\u202e\u202d\u202a\u202b\u202c'
                    '\u2066\u2067\u2068\u2069\u2028\u2029'
                    + ''.join(chr(value) for value in range(0x7f, 0xa0)))
        plan = fixture_plan()
        hostile_path = 'C:\\DecisionFixture\\display' + controls + '.exe'
        plan['candidates'][0]['path'] = hostile_path
        item = choice(path=hostile_path)
        item.update(explanation='Review' + controls + 'this proposal',
                    consequence='No execution' + controls + 'is authorized')
        for language in ('zh', 'en'):
            with self.subTest(language=language):
                rendered = report.render_report(plan, scenarios(item), language=language)
                for control in controls:
                    self.assertNotIn(control, rendered, f'Raw U+{ord(control):04X} can hide or reorder report text')
                self.assertIn('.exe', visible_text(rendered))

    def test_disallowed_c0_or_surrogate_text_is_rejected_before_rendering(self):
        for control in ('\x00', '\x07', '\x1b', '\ud800'):
            plan = fixture_plan()
            plan['candidates'][0]['path'] = 'C:\\DecisionFixture\\bad' + control + '.exe'
            with self.subTest(control=repr(control)), self.assertRaises(ValueError):
                report.render_report(plan, language='en')


class DecisionScenarioTests(unittest.TestCase):
    def analyze(self, plan=None, item=None):
        result = report.analyze_scenarios(fixture_plan() if plan is None else plan,
                                          scenarios(choice() if item is None else item))
        self.assertEqual(len(result), 1)
        return result[0]

    def test_copy_scope_is_hypothetical_never_reclaimed_or_authorized(self):
        result = self.analyze()
        self.assertEqual(result['selected_logical_copy_scope_bytes'], 20 * GIB)
        self.assertEqual(result['proposed_file_count'], 1)
        self.assertEqual(result['unselected_file_count'], 1)
        self.assertFalse(result['destination_identity_verified'])
        self.assertFalse(result['authorization'])
        self.assertIsNone(result['actual_reclaimed_bytes'])
        # The proposed logical scope exceeds the 15 GiB shortfall, but this is
        # not evidence that cleanup ran or the free-space goal was achieved.
        self.assertIsNone(result['goal_achieved'])

    def test_directory_overlaps_never_inflate_file_copy_scope(self):
        plan = fixture_plan()
        original = self.analyze(plan)
        plan['directory_reviews'][0]['logical_bytes'] = 5000 * GIB
        plan['directory_reviews'][1]['logical_bytes'] = 4000 * GIB
        changed = self.analyze(plan)
        self.assertEqual(original['selected_logical_copy_scope_bytes'], 20 * GIB)
        self.assertEqual(changed['selected_logical_copy_scope_bytes'], original['selected_logical_copy_scope_bytes'])
        self.assertIsNone(changed['actual_reclaimed_bytes'])

    def test_same_or_unresolved_destination_gives_no_copy_scope_credit(self):
        for destination in ('volume-c', None):
            with self.subTest(destination=destination):
                result = self.analyze(item=choice(destination=destination))
                self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
                self.assertEqual(result['rows'][0]['counted_logical_bytes'], 0)
                self.assertIsNone(result['goal_achieved'])

    def test_wrong_or_unknown_source_volume_gives_no_copy_scope_credit(self):
        for volume in ('volume-other', None):
            with self.subTest(volume=volume):
                plan = fixture_plan()
                plan['candidates'][0]['volume_id'] = volume
                result = self.analyze(plan)
                self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
                self.assertEqual(result['rows'][0]['counted_logical_bytes'], 0)

    def test_absent_goal_volume_cannot_establish_cross_volume_credit(self):
        plan = fixture_plan()
        plan.update(goal_kind='additional_free_space', goal_volume=None, baseline_free_bytes=None,
                    required_additional_bytes=plan['goal_bytes'], capacity_snapshot_status='additional_space_requested')
        result = self.analyze(plan)
        self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)

    def test_hardlinked_file_gives_no_copy_scope_credit(self):
        plan = fixture_plan()
        plan['candidates'][0]['hardlink_count'] = 2
        result = self.analyze(plan)
        self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
        self.assertEqual(result['rows'][0]['scope_status'], 'excluded_hardlinks')

    def test_managed_or_cache_files_give_no_copy_scope_credit(self):
        for category in ('application_data', 'possible_temp_or_cache', 'system_managed'):
            with self.subTest(category=category):
                plan = fixture_plan()
                plan['candidates'][0]['category'] = category
                result = self.analyze(plan)
                self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
                self.assertEqual(result['rows'][0]['counted_logical_bytes'], 0)

    def test_known_managed_paths_cannot_gain_credit_through_ordinary_category(self):
        for path in ('C:\\DecisionFixture\\AppData\\Local\\runtime.zip',
                     'C:\\DecisionFixture\\project\\.git\\objects\\pack\\large.pack',
                     'C:\\DecisionFixture\\project\\.svn\\pristine\\large.bin',
                     'C:\\DecisionFixture\\OneDrive - Example\\archive.zip',
                     'C:\\DecisionFixture\\Dropbox\\archive.zip',
                     'C:\\DecisionFixture\\Google Drive\\archive.zip'):
            with self.subTest(path=path):
                plan = fixture_plan()
                plan['candidates'][0].update(path=path, category='user_file')
                result = self.analyze(plan, choice(path=path))
                self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
                self.assertEqual(result['rows'][0]['scope_status'], 'excluded_managed_category')

    def test_keep_review_and_app_cleanup_never_claim_released_space(self):
        for action in ('keep', 'review', 'app_cleanup'):
            with self.subTest(action=action):
                result = self.analyze(item=choice(action=action))
                self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
                self.assertIsNone(result['actual_reclaimed_bytes'])
                self.assertIsNone(result['goal_achieved'])
                self.assertFalse(result['authorization'])

    def test_missing_choices_imply_no_proposed_action(self):
        results = report.analyze_scenarios(fixture_plan(), None)
        for result in results:
            self.assertEqual(result['proposed_file_count'], 0)
            self.assertEqual(result['selected_logical_copy_scope_bytes'], 0)
            self.assertFalse(result['authorization'])
        text = report.render_report(fixture_plan(), language='en')
        self.assertRegex(text.lower(), r'no proposed action|not selected|no choices|no actions proposed')

    def test_two_scenarios_are_alternatives_not_combined(self):
        inputs = scenarios(choice())
        inputs['scenarios'].append({'name': 'expanded', 'choices': [choice(), choice(path=SECOND_FILE)]})
        results = report.analyze_scenarios(fixture_plan(), inputs)
        self.assertEqual([item['selected_logical_copy_scope_bytes'] for item in results], [20 * GIB, 22 * GIB])
        self.assertTrue(all(item['goal_achieved'] is None for item in results))

    def test_inconsistent_capacity_snapshot_is_rejected(self):
        plan = fixture_plan()
        plan['required_additional_bytes'] = 1
        with self.assertRaises(ValueError):
            report.render_report(plan, language='en')

    def test_boolean_byte_counts_do_not_pass_as_integers(self):
        plan = fixture_plan()
        plan['candidates'][0]['logical_bytes'] = True
        with self.assertRaises(ValueError):
            report.render_report(plan, language='en')

    def test_historically_met_target_still_does_not_claim_current_achievement(self):
        plan = fixture_plan()
        plan['goal_volume'].update(free_bytes=25 * GIB, used_bytes=75 * GIB)
        plan.update(baseline_free_bytes=25 * GIB, required_additional_bytes=0,
                    capacity_snapshot_status='already_at_free_target_at_scan_time')
        result = self.analyze(plan)
        self.assertIsNone(result['goal_achieved'])
        self.assertIsNone(result['actual_reclaimed_bytes'])


if __name__ == '__main__':
    unittest.main()
