"""Offline app-turn lifecycle contracts; every response and account is synthetic."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
from coda_review_hub import cli


class HandoffContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests('test_fresh_observation_and_exact_packet_bytes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)
        self.ref = 'synthetic-saved-project-conversation'

    def prepared(self, reference=None):
        test_core.seed_models(self.hub)
        return self.hub.handoff(
            self.project, 'chatgpt', 'Review only this synthetic fixture.',
            self.ref if reference is None else reference)['job']

    def record(self, job, response='Synthetic observed answer.', **overrides):
        arguments = dict(project=self.project, job_id=job['id'], response=response,
                         evidence='Synthetic saved conversation and observed response only.',
                         conversation_ref=self.ref)
        arguments.update(overrides)
        return self.hub.record_handoff_result(**arguments)['job']

    @staticmethod
    def observation(status='completed', *, outstanding=(), resolved=(), **overrides):
        value = {'status': status,
                 'continue_available': status in ('tool_limit', 'output_limit'),
                 'outstanding_checks': list(outstanding), 'resolved_checks': list(resolved)}
        value.update(overrides)
        return value

    @staticmethod
    def envelope():
        return {'schema_version': 1, 'summary': 'Synthetic normalized conclusion.', 'findings': []}

    @staticmethod
    def turn_path(job, turn):
        return Path(job['evidence_directory']) / 'handoff-turns' / turn['turn_id'] / 'answer.txt'

    def test_missing_completion_observation_preserves_unknown_partial(self):
        job = self.prepared()
        response = 'A verdict-shaped answer is not evidence that every check finished.'
        with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
            recorded = self.record(job, response)
        self.assertEqual(recorded['state'], 'needs_continuation')
        self.assertEqual(recorded['completion']['status'], 'unknown')
        self.assertEqual(recorded['acknowledgment'], 'pending')
        self.assertEqual(len(recorded['handoff_turns']), 1)
        self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
        self.assertEqual(self.hub.result(self.project, job['id'])['answer'], response)
        finalize.assert_not_called()
        self.fixture.launch.assert_not_called()

    def test_ui_finished_and_verdict_do_not_override_explicit_tool_limit(self):
        job = self.prepared()
        response = ('Verdict: the design appears sound.\r\n'
                    'I hit the tool limit. Select Continue to finish the source checks.\r\n')
        with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
            recorded = self.record(job, response, completion_observation=self.observation('completed'),
                                   evidence='Synthetic UI reports response finished; source checks are unfinished.')
        self.assertEqual(recorded['state'], 'needs_continuation')
        self.assertEqual(recorded['completion']['status'], 'tool_limit')
        self.assertFalse(recorded['completion_eligible'])
        self.assertNotIn('finished_at', recorded)
        self.assertNotIn('answer_sha256', recorded)
        finalize.assert_not_called()

    def test_claude_tool_call_notice_blocks_findings_then_allows_same_conversation_finish(self):
        # Reproduced failure: ordinary "tool call" wording was not recognized;
        # reported completion finalized the job and made continuation impossible.
        for provider in ('claude-desktop', 'claude-cowork'):
            with self.subTest(provider=provider):
                test_core.seed_models(self.hub)
                job = self.hub.handoff(self.project, provider, 'Review this synthetic audit only.', self.ref)['job']
                original = 'Tool call limit reached. Please click Continue so I can finish the audit.\r\n'
                with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
                    partial = self.record(job, original, completion_observation=self.observation(
                        'completed', provider_stop_reason='end_turn'),
                        evidence='Synthetic app UI shows tool call limit reached with Continue available.')
                    self.assertEqual(partial['state'], 'needs_continuation')
                    self.assertEqual(partial['completion']['status'], 'tool_limit')
                    self.assertFalse(partial['completion_eligible'])
                    self.assertEqual(partial['acknowledgment'], 'pending')
                    self.assertNotIn('finished_at', partial)
                    self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
                    with self.assertRaisesRegex(ValueError, 'actually returned'):
                        self.hub.record_review(self.project, job['id'], self.envelope(),
                                               'Synthetic normalization audit only.')
                    with self.assertRaisesRegex(ValueError, 'cannot enter comparison'):
                        self.hub.comparison_report(self.project, [job['id']])
                    finalize.assert_not_called()
                    turn = partial['handoff_turns'][-1]
                    final_text = 'The remaining source checks are now complete. Synthetic final review.'
                    completed = self.record(job, final_text, previous_turn_id=turn['turn_id'],
                                            completion_observation=self.observation('completed'),
                                            acknowledgment='delivered')
                    self.assertEqual(completed['state'], 'returned_via_handoff')
                    self.assertEqual(self.hub.result(self.project, job['id'])['answer'], final_text)
                    self.assertEqual(self.turn_path(partial, turn).read_bytes(), original.encode('utf-8'))
                    self.assertEqual(completed['handoff_turns'][-1]['previous_answer_sha256'], turn['answer_sha256'])
                    review = self.hub.record_review(self.project, job['id'], self.envelope(),
                                                   'Synthetic completed normalization audit only.')
                    self.assertEqual(review['summary'], self.envelope()['summary'])
                    finalize.assert_called_once()
        self.fixture.launch.assert_not_called()

    def test_interruption_categories_remain_distinct_and_never_finalize(self):
        for status in ('tool_limit', 'output_limit', 'cancelled', 'provider_error',
                       'delivery_unknown', 'incomplete', 'unknown'):
            with self.subTest(status=status):
                job = self.prepared()
                with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
                    recorded = self.record(job, 'Synthetic interrupted response.',
                                           completion_observation=self.observation(status))
                self.assertEqual(recorded['completion']['status'], status)
                self.assertEqual(recorded['state'], 'needs_continuation')
                self.assertFalse(recorded['completion_eligible'])
                self.assertEqual(recorded['acknowledgment'], 'pending')
                self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
                finalize.assert_not_called()

    def test_crlf_partial_and_hash_remain_immutable_after_single_finalization(self):
        job = self.prepared()
        first_text = 'Synthetic preliminary result.\r\nOne source check remains.\r\n'
        final_text = 'Synthetic source check completed.\r\nThe final conclusion is bounded.\r\n'
        with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
            first = self.record(job, first_text, completion_observation=self.observation(
                'tool_limit', outstanding=['inspect synthetic boundary']))
            prior = deepcopy(first['handoff_turns'][0])
            first_path = self.turn_path(first, prior)
            first_bytes = first_path.read_bytes()
            self.assertEqual(first_bytes, first_text.encode('utf-8'))
            self.assertEqual(prior['answer_sha256'], hashlib.sha256(first_bytes).hexdigest())
            self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
            finalize.assert_not_called()
            finished = self.record(job, final_text, previous_turn_id=prior['turn_id'],
                                   completion_observation=self.observation(
                                       resolved=['inspect synthetic boundary']), acknowledgment='delivered')
            self.assertEqual(finished['state'], 'returned_via_handoff')
            self.assertTrue(finished['completion_eligible'])
            self.assertEqual(finished['handoff_turns'][0], prior)
            final_turn = finished['handoff_turns'][1]
            self.assertEqual(final_turn['previous_turn_id'], prior['turn_id'])
            self.assertEqual(final_turn['previous_answer_sha256'], prior['answer_sha256'])
            self.assertEqual(final_turn['conversation_ref'], prior['conversation_ref'])
            self.assertEqual(finished['completion_turn_id'], final_turn['turn_id'])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertEqual((Path(job['evidence_directory']) / 'answer.txt').read_bytes(), final_text.encode('utf-8'))
            self.assertEqual(self.hub.result(self.project, job['id'])['answer'], final_text)
            page = self.hub.result(self.project, job['id'], offset=10, limit=17, turn_id=prior['turn_id'])
            self.assertEqual(page['answer'], first_text[10:27])
            self.assertEqual(page['turn_id'], prior['turn_id'])
            finalize.assert_called_once()
            with self.assertRaises(ValueError):
                self.record(job, final_text, previous_turn_id=final_turn['turn_id'],
                            completion_observation=self.observation())
            finalize.assert_called_once()
        self.fixture.launch.assert_not_called()

    def test_all_prior_outstanding_checks_must_be_resolved_across_turns(self):
        job = self.prepared()
        first = self.record(job, completion_observation=self.observation(
            'tool_limit', outstanding=['check alpha', 'check beta']))
        second = self.record(job, 'Synthetic alpha check is complete.',
                             previous_turn_id=first['handoff_turns'][-1]['turn_id'],
                             completion_observation=self.observation(resolved=['check alpha']))
        self.assertEqual(second['state'], 'needs_continuation')
        self.assertIn('check beta', second['completion']['outstanding_checks'])
        self.assertNotIn('check alpha', second['completion']['outstanding_checks'])
        third = self.record(job, 'Synthetic beta check is complete.',
                            previous_turn_id=second['handoff_turns'][-1]['turn_id'],
                            completion_observation=self.observation(resolved=['check beta']))
        self.assertEqual(third['state'], 'returned_via_handoff')
        self.assertEqual(third['completion']['outstanding_checks'], [])
        self.assertEqual(len(third['handoff_turns']), 3)

    def test_continuation_requires_exact_latest_parent_and_conversation(self):
        job = self.prepared()
        first = self.record(job)
        parent = first['handoff_turns'][-1]['turn_id']
        other = self.record(self.prepared())
        foreign_parent = other['handoff_turns'][-1]['turn_id']
        for changes in ({}, {'previous_turn_id': '0' * 32}, {'previous_turn_id': foreign_parent},
                        {'previous_turn_id': parent, 'conversation_ref': 'different-synthetic-conversation'},
                        {'previous_turn_id': parent, 'project': str(self.fixture.other_project)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.record(job, completion_observation=self.observation(), **changes)
        current = self.hub.result(self.project, job['id'])['job']
        self.assertEqual(current['handoff_turns'], first['handoff_turns'])
        second = self.record(job, previous_turn_id=parent)
        with self.assertRaises(ValueError):
            self.record(job, previous_turn_id=parent, completion_observation=self.observation())
        self.assertEqual(len(second['handoff_turns']), 2)

    def test_new_conversation_binds_first_observed_reference_then_refuses_switch(self):
        job = self.prepared(reference='')
        first = self.record(job)
        self.assertEqual(first['conversation_ref'], self.ref)
        with self.assertRaises(ValueError):
            self.record(job, previous_turn_id=first['handoff_turns'][-1]['turn_id'],
                        conversation_ref='another-synthetic-conversation',
                        completion_observation=self.observation())

    def test_pending_review_lineage_comparison_and_closing_ack_are_refused(self):
        earlier = self.prepared()
        early = self.record(earlier)
        complete_job = self.prepared()
        self.record(complete_job, completion_observation=self.observation())
        later = self.prepared()
        self.record(later)
        with self.assertRaises(ValueError):
            self.hub.record_review(self.project, earlier['id'], self.envelope(), 'Synthetic normalization evidence.')
        for child, parent in ((complete_job, earlier), (later, complete_job)):
            with self.subTest(child=child['id']), self.assertRaises(ValueError):
                self.hub.record_lineage(self.project, child['id'], parent['id'],
                                        'app_conversation', 'Synthetic same-conversation observation.')
        for format in ('html', 'markdown'):
            with self.subTest(format=format), self.assertRaises(ValueError):
                self.hub.comparison_report(self.project, [complete_job['id'], earlier['id']], format)
        for acknowledgment in ('delivered', 'not_possible'):
            with self.subTest(acknowledgment=acknowledgment), self.assertRaises(ValueError):
                self.record(earlier, previous_turn_id=early['handoff_turns'][-1]['turn_id'],
                            acknowledgment=acknowledgment,
                            completion_observation=self.observation('tool_limit'))
        self.assertEqual(len(self.hub.result(self.project, earlier['id'])['job']['handoff_turns']), 1)

    def test_completed_review_and_lineage_unlock_only_after_continuation(self):
        first_job, second_job = self.prepared(), self.prepared()
        first_partial = self.record(first_job)
        second_partial = self.record(second_job)
        for job, partial in ((first_job, first_partial), (second_job, second_partial)):
            self.record(job, previous_turn_id=partial['handoff_turns'][-1]['turn_id'],
                        completion_observation=self.observation())
        review = self.hub.record_review(self.project, second_job['id'], self.envelope(),
                                       'Synthetic completed response normalization.')
        self.assertEqual(review['summary'], self.envelope()['summary'])
        lineage = self.hub.record_lineage(self.project, second_job['id'], first_job['id'],
                                           'app_conversation', 'Synthetic completed same-conversation observation.')
        self.assertEqual(lineage['parent_job_id'], first_job['id'])
        report = self.hub.comparison_report(self.project, [first_job['id'], second_job['id']])
        self.assertIn('Synthetic normalized conclusion.', report['content'])

    def test_prior_turn_tamper_blocks_continuation_and_explicit_read(self):
        job = self.prepared()
        partial = self.record(job)
        turn = partial['handoff_turns'][0]
        self.turn_path(partial, turn).write_bytes(b'Changed synthetic fixture bytes.')
        with self.assertRaises(ValueError):
            self.record(job, previous_turn_id=turn['turn_id'], completion_observation=self.observation())
        with self.assertRaises(ValueError):
            self.hub.result(self.project, job['id'], turn_id=turn['turn_id'])
        self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())

    def test_per_turn_returned_files_preserve_earlier_snapshot(self):
        job = self.prepared()
        source = self.fixture.project / 'synthetic-return.txt'
        source.write_bytes(b'first artifact\r\n')
        first = self.record(job, returned_files=[str(source)],
                            artifact_evidence='Synthetic observed first returned-file origin.')
        first_turn = first['handoff_turns'][0]
        first_files = self.hub.attachment_files(self.project, job['id'], 'output', first_turn['turn_id'])
        first_path = Path(first_files['upload_paths'][0])
        source.write_bytes(b'second artifact\r\n')
        final = self.record(job, previous_turn_id=first_turn['turn_id'], returned_files=[str(source)],
                            artifact_evidence='Synthetic observed second returned-file origin.',
                            completion_observation=self.observation())
        latest = self.hub.attachment_files(self.project, job['id'], direction='output')
        self.assertNotEqual(first_files['upload_paths'], latest['upload_paths'])
        self.assertEqual(first_path.read_bytes(), b'first artifact\r\n')
        self.assertEqual(Path(latest['upload_paths'][0]).read_bytes(), b'second artifact\r\n')
        self.assertEqual(final['handoff_turns'][0], first_turn)

    def test_turn_read_cannot_cross_job_or_project_scope(self):
        first_job, second_job = self.prepared(), self.prepared()
        first = self.record(first_job)
        self.record(second_job)
        identifier = first['handoff_turns'][0]['turn_id']
        for project, job in ((self.project, second_job), (str(self.fixture.other_project), first_job)):
            with self.subTest(project=project, job=job['id']), self.assertRaises(ValueError):
                self.hub.result(project, job['id'], turn_id=identifier)

    def test_concurrent_same_parent_completion_finalizes_only_once(self):
        job = self.prepared()
        partial = self.record(job)
        parent = partial['handoff_turns'][0]['turn_id']

        def finish():
            try:
                return self.record(job, previous_turn_id=parent,
                                   completion_observation=self.observation())['state']
            except ValueError:
                return 'rejected'

        with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: finish(), range(2)))
            self.assertCountEqual(results, ['returned_via_handoff', 'rejected'])
            finalize.assert_called_once()
        completed = self.hub.result(self.project, job['id'])['job']
        self.assertEqual(len(completed['handoff_turns']), 2)

    def test_legacy_returned_receipt_remains_readable_without_reclassification(self):
        job = self.prepared()
        answer = b'Synthetic legacy answer.\r\n'
        (Path(job['evidence_directory']) / 'answer.txt').write_bytes(answer)
        # Model a pre-continuation receipt, not a newly recorded answer lacking
        # completion evidence. No production state or migration is modified.
        with self.hub.connect() as connection:
            row = self.hub._job(connection, test_core.core.project_path(self.project), job['id'])
            self.hub._update(connection, row, state='returned_via_handoff',
                             submission='coordinator_observed_response',
                             answer_sha256=hashlib.sha256(answer).hexdigest())
        read = self.hub.result(self.project, job['id'])
        self.assertEqual(read['answer'], answer.decode('utf-8'))
        self.assertEqual(read['turn_id'], '')
        self.assertNotIn('handoff_turns', read['job'])
        review = self.hub.record_review(self.project, job['id'], self.envelope(),
                                       'Synthetic normalization of a legacy receipt.')
        self.assertEqual(review['source_answer_sha256'], hashlib.sha256(answer).hexdigest())
        self.assertTrue(self.hub.comparison_report(self.project, [job['id']])['content'])

    def test_interrupted_empty_response_is_saved_but_cannot_be_a_completed_answer(self):
        job = self.prepared()
        partial = self.record(job, '', completion_observation=self.observation('cancelled'))
        self.assertEqual(partial['state'], 'needs_continuation')
        self.assertEqual(partial['completion']['status'], 'cancelled')
        self.assertEqual(self.hub.result(self.project, job['id'])['answer'], '')
        with self.assertRaises(ValueError):
            self.record(job, '', previous_turn_id=partial['handoff_turns'][0]['turn_id'],
                        completion_observation=self.observation())
        self.assertEqual(len(self.hub.result(self.project, job['id'])['job']['handoff_turns']), 1)

    def test_failed_job_update_cannot_create_final_cache_or_block_receipt_retry(self):
        job = self.prepared()
        partial = self.record(job, 'Synthetic preserved partial.\r\n')
        prior = deepcopy(partial['handoff_turns'][0])
        prior_bytes = self.turn_path(partial, prior).read_bytes()
        final_text = 'Synthetic final answer after the remaining checks.\r\n'
        with patch.object(self.hub, '_finalize_handoff', wraps=self.hub._finalize_handoff) as finalize:
            with patch.object(self.hub, '_update', side_effect=OSError('Synthetic metadata-write failure')):
                with self.assertRaises(OSError):
                    self.record(job, final_text, previous_turn_id=prior['turn_id'],
                                completion_observation=self.observation())
            finalize.assert_not_called()
            current = self.hub.result(self.project, job['id'])['job']
            self.assertEqual(current['state'], 'needs_continuation')
            self.assertEqual(current['handoff_turns'], [prior])
            self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
            self.assertEqual(self.turn_path(current, prior).read_bytes(), prior_bytes)
            completed = self.record(job, final_text, previous_turn_id=prior['turn_id'],
                                    completion_observation=self.observation())
            self.assertEqual(completed['state'], 'returned_via_handoff')
            self.assertEqual(len(completed['handoff_turns']), 2)
            self.assertEqual(completed['handoff_turns'][0], prior)
            self.assertEqual(self.hub.result(self.project, job['id'])['answer'], final_text)
            finalize.assert_called_once()
        self.fixture.launch.assert_not_called()

    def test_final_cache_failure_does_not_lose_committed_completion_or_allow_duplicate(self):
        job = self.prepared()
        partial = self.record(job)
        parent = partial['handoff_turns'][0]['turn_id']
        final_text = 'Synthetic durable completed answer.\r\n'
        with patch.object(self.hub, '_finalize_handoff', side_effect=OSError('Synthetic final-cache failure')) as finalize:
            try:
                self.record(job, final_text, previous_turn_id=parent,
                            completion_observation=self.observation())
            except OSError:
                # The CLI may report a cache-write failure; the completed turn
                # must nevertheless remain canonical, readable, and nonrepeatable.
                pass
            finalize.assert_called_once()
            completed = self.hub.result(self.project, job['id'])
            self.assertEqual(completed['job']['state'], 'returned_via_handoff')
            self.assertTrue(completed['job']['completion_eligible'])
            self.assertEqual(completed['answer'], final_text)
            self.assertEqual(len(completed['job']['handoff_turns']), 2)
            final_turn = completed['job']['handoff_turns'][-1]
            self.assertEqual(completed['job']['completion_turn_id'], final_turn['turn_id'])
            self.assertFalse((Path(job['evidence_directory']) / 'answer.txt').exists())
            self.assertEqual(self.hub.result(self.project, job['id'], turn_id=final_turn['turn_id'])['answer'], final_text)
            self.hub.record_review(self.project, job['id'], self.envelope(),
                                   'Synthetic review of the durable completion, without final cache.')
            with self.assertRaises(ValueError):
                self.record(job, final_text, previous_turn_id=final_turn['turn_id'],
                            completion_observation=self.observation())
            finalize.assert_called_once()
        self.fixture.launch.assert_not_called()

    def test_cli_completion_payload_continuation_and_explicit_turn_passthrough(self):
        job = self.prepared()
        request = self.fixture.root / 'synthetic-handoff-receipt.json'
        first_text = 'Synthetic first response.\r\nAdditional source review is pending.\r\n'
        payload = dict(project=self.project, job_id=job['id'], response=first_text,
                       evidence='Synthetic saved app response and current observed status.',
                       conversation_ref=self.ref,
                       completion_observation=self.observation('tool_limit', outstanding=['review synthetic index']))

        def run(arguments):
            output = io.StringIO()
            with patch.object(cli, 'Hub', return_value=self.hub), redirect_stdout(output):
                self.assertEqual(cli.main(arguments), 0)
            return json.loads(output.getvalue())

        request.write_text(json.dumps(payload), encoding='utf-8')
        first = run(['record-handoff-result', str(request)])['job']
        self.assertEqual(first['state'], 'needs_continuation')
        self.assertEqual(first['completion']['status'], 'tool_limit')
        prior = first['handoff_turns'][0]
        payload.update(response='Synthetic final index review is complete.\r\n',
                       previous_turn_id=prior['turn_id'],
                       completion_observation=self.observation(resolved=['review synthetic index']))
        request.write_text(json.dumps(payload), encoding='utf-8')
        finished = run(['record-handoff-result', str(request)])['job']
        self.assertEqual(finished['state'], 'returned_via_handoff')
        self.assertEqual(finished['handoff_turns'][-1]['previous_turn_id'], prior['turn_id'])
        reread = run(['result', '--project', self.project, '--job-id', job['id'], '--turn-id', prior['turn_id']])
        self.assertEqual(reread['turn_id'], prior['turn_id'])
        self.assertEqual(reread['answer'], first_text)
        self.assertEqual(reread['job']['handoff_turns'][0]['answer_sha256'], hashlib.sha256(first_text.encode('utf-8')).hexdigest())
        self.fixture.launch.assert_not_called()

    def test_atomic_cache_publication_failure_leaves_canonical_answer_readable(self):
        job = self.prepared()
        final_text = 'Synthetic complete answer with preserved line endings.\r\n'
        directory = Path(job['evidence_directory'])

        def fail_publish(source, target):
            self.assertEqual(Path(source).read_bytes(), final_text.encode('utf-8'))
            self.assertFalse(Path(target).exists())
            # The immutable response and completed binding must be committed
            # before publishing the optional cache, so another reader is safe.
            concurrent_read = self.hub.result(self.project, job['id'])
            self.assertEqual(concurrent_read['job']['state'], 'returned_via_handoff')
            self.assertEqual(concurrent_read['answer'], final_text)
            raise OSError('Synthetic atomic cache-publication failure')

        with patch('coda_review_hub.core.os.link', side_effect=fail_publish) as publish:
            with self.assertRaises(OSError):
                self.record(job, final_text, completion_observation=self.observation())
            publish.assert_called_once()
            completed = self.hub.result(self.project, job['id'])
            self.assertEqual(completed['answer'], final_text)
            self.assertEqual(len(completed['job']['handoff_turns']), 1)
            self.assertFalse((directory / 'answer.txt').exists())
            self.assertEqual(list(directory.glob('.completed-answer-*.tmp')), [])
            with self.assertRaises(ValueError):
                self.record(job, final_text, previous_turn_id=completed['job']['completion_turn_id'],
                            completion_observation=self.observation())
            publish.assert_called_once()
        self.fixture.launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
