"""Consumer Muse browser contracts using isolated, synthetic observations only."""
from datetime import datetime, timezone
from pathlib import Path
import unittest

import test_core
from coda_review_hub import core
from coda_review_hub.capabilities import handoff_route_metadata, route_capabilities


class MetaMuseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.HubTests('test_fresh_observation_and_exact_packet_bytes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.hub = self.fixture.hub
        self.project = str(self.fixture.project)

    def observe_muse(self, *, model='provider-managed', choose=True):
        status = self.hub.record_models('meta-muse', [
            {'id': model, 'label': 'Synthetic observed provider-managed mode', 'efforts': ['default']}
        ], 'Synthetic signed-in app observation: provider-managed mode, no adjustable picker.',
            datetime.now(timezone.utc).isoformat())
        if choose:
            self.hub.select_model('meta-muse', model, 'default', status['catalog']['fingerprint'],
                                  'Explicit synthetic user choice of the observed mode only.')
        return status

    def test_browser_metadata_is_additive_fresh_and_does_not_claim_account_capabilities(self):
        listing = self.hub.routes()
        route = next(item for item in listing['routes'] if item['provider'] == 'meta-muse')
        metadata = handoff_route_metadata('meta-muse')
        for key, value in metadata.items():
            self.assertEqual(route[key], value)
        self.assertEqual(metadata['entry_url'], 'https://muse.ai/')
        self.assertEqual(metadata['app_surface'], 'browser')
        self.assertEqual(metadata['agent_runtime'], 'provider_cloud')
        self.assertEqual(metadata['dispatch_mode'], 'manual_coordinator')
        self.assertEqual(metadata['billing_enforcement'], 'coordinator_observation_only')
        self.assertIn('Muse Code is a separate', metadata['entitlement_note'])
        self.assertFalse(route['live_ready'])
        self.assertEqual(listing['route_counts'], {'automated': 4, 'coordinator_handoff': 11, 'retired': 1})
        capability = route_capabilities('meta-muse')
        for key, value in metadata.items():
            self.assertEqual(capability[key], value)
        for field in ('image_visual_input', 'document_binary_input', 'session_resume'):
            self.assertIsNone(capability[field])
        for field in ('upload_claimed', 'provider_acceptance_verified', 'provider_interpretation_verified'):
            self.assertFalse(capability[field])
        for requirement in ('named project-specific side chat', 'fresh included usage',
                            'not a Hub-enforced app billing gate', 'provider-managed mode',
                            'attachment chips', 'do not enable new connectors'):
            self.assertIn(requirement, route['instructions'])
        metadata['required_observations'].clear()
        route['required_observations'].append('invented observation')
        fresh = handoff_route_metadata('meta-muse')
        self.assertIn('saved_project_side_chat', fresh['required_observations'])
        self.assertNotIn('invented observation', fresh['required_observations'])
        self.assertEqual(handoff_route_metadata('meta-ai'), {})
        self.assertNotIn('entry_url', route_capabilities('meta-ai'))
        self.fixture.launch.assert_not_called()

    def test_muse_model_choice_and_fresh_app_observation_remain_required(self):
        changed = self.observe_muse(choose=False)
        self.assertTrue(changed['selection_required'])
        with self.assertRaisesRegex(ValueError, 'choose a model'):
            self.hub.handoff(self.project, 'meta-muse', 'Synthetic bounded packet only.')
        self.assertEqual(self.hub.jobs(self.project), [])
        self.hub.select_model('meta-muse', 'provider-managed', 'default', changed['catalog']['fingerprint'],
                              'Explicit synthetic user choice of observed provider-managed mode.')
        self.hub.handoff(self.project, 'meta-muse', 'Synthetic bounded packet only.')
        with self.assertRaisesRegex(ValueError, 'Refresh'):
            self.hub.handoff(self.project, 'meta-muse', 'A second send needs a fresh observation.')
        current = self.observe_muse(model='new-observed-mode', choose=False)
        self.assertTrue(current['selection_required'])
        with self.assertRaisesRegex(ValueError, 'choose a model'):
            self.hub.handoff(self.project, 'meta-muse', 'Do not silently change observed modes.')
        self.fixture.launch.assert_not_called()

    def test_provider_managed_preparation_does_not_invent_picker_or_thinking_controls(self):
        self.observe_muse()
        prepared = self.hub.handoff(self.project, 'meta-muse', 'Synthetic no-picker review only.')
        job = prepared['job']
        self.assertEqual(job['model'], 'provider-managed')
        self.assertEqual(job['effort'], 'default')
        self.assertFalse(job['backend_model_verified'])
        self.assertFalse(prepared['sent'])
        self.assertIn('model options or explicitly provider-managed mode', job['model_selection_basis'])
        self.assertIn('local descriptors do not verify backend identity', job['model_selection_basis'])
        self.assertIn('verify again at actual send', job['model_selection_basis'])
        self.assertNotIn('Coordinator-observed picker at preparation', job['model_selection_basis'])
        instructions = job['instructions']
        self.assertIn('Saved local selection descriptor: provider-managed; effort descriptor: default', instructions)
        self.assertIn('only when the corresponding control is actually offered', instructions)
        self.assertIn('default descriptor does not assert an exposed thinking level', instructions)
        self.assertNotIn("use the user's saved model provider-managed", instructions)
        self.assertNotIn('thinking level default', instructions)
        self.assertFalse(core.Hub(self.hub.state).result(self.project, job['id'])['job']['backend_model_verified'])
        self.fixture.launch.assert_not_called()

    def test_exact_files_and_interrupted_review_complete_only_in_same_saved_side_chat(self):
        self.observe_muse()
        source = self.fixture.project / 'synthetic-document.pdf'
        original = b'%PDF-synthetic-fixture\x00\xff\r\nOriginal bytes; not a rendered PDF.'
        source.write_bytes(original)
        first_output = self.fixture.project / 'first-observed-output.bin'
        first_bytes = b'\x00\x80synthetic returned artifact, first turn'
        first_output.write_bytes(first_bytes)
        last_output = self.fixture.project / 'final-observed-output.bin'
        last_output.write_bytes(b'\xffsynthetic returned artifact, final turn')
        reference = 'synthetic-saved-muse-project-side-chat'
        prepared = self.hub.handoff(self.project, 'meta-muse', 'Review only this synthetic document.',
                                    reference, attachments=[str(source)])
        job = prepared['job']
        self.assertFalse(prepared['sent'])
        self.assertEqual(job['submission'], 'not_sent')
        self.assertEqual(job['state'], 'awaiting_handoff')
        self.assertEqual(job['model'], 'provider-managed')
        self.assertEqual(job['effort'], 'default')
        for key, value in handoff_route_metadata('meta-muse').items():
            self.assertEqual(job[key], value)
        self.assertIn('normal saved, non-Temporary', job['instructions'])
        self.assertNotIn(str(source), prepared['packet'])
        files = self.hub.attachment_files(self.project, job['id'])
        self.assertFalse(files['sent'])
        self.assertEqual(Path(files['upload_paths'][0]).read_bytes(), original)
        source.write_bytes(b'changed source must not alter the recorded input')
        self.assertEqual(Path(files['upload_paths'][0]).read_bytes(), original)
        common = dict(
            project=self.project, job_id=job['id'], conversation_ref=reference,
            evidence='Synthetic observation: named project side chat saved before sending and reopened afterward.',
            observed_attachment_ids=[item['attachment_id'] for item in files['manifest']],
            attachment_evidence='Synthetic observed accepted PDF attachment chip matches the exact allowlist.',
            artifact_evidence='Synthetic download provenance, exact project-local returned artifact.',
            observed_model='', observed_mode='Provider-managed (synthetic observation)',
        )
        partial_text = 'First check recorded.\r\nTool call limit reached; inspect the remaining diagram.'
        partial = self.hub.record_handoff_result(
            **common, response=partial_text, returned_files=[str(first_output)],
            completion_observation={'status': 'tool_limit', 'continue_available': True,
                                    'outstanding_checks': ['Inspect remaining diagram']})['job']
        self.assertEqual(partial['state'], 'needs_continuation')
        self.assertEqual(partial['acknowledgment'], 'pending')
        self.assertFalse(partial['backend_model_verified'])
        self.assertFalse(partial['completion_eligible'])
        self.assertEqual(self.hub.result(self.project, job['id'])['answer'], partial_text)
        turn = partial['handoff_turns'][-1]
        with self.assertRaisesRegex(ValueError, 'actually returned'):
            self.hub.record_review(self.project, job['id'],
                                   {'schema_version': 1, 'summary': 'Synthetic review.', 'findings': []},
                                   'Synthetic normalization is blocked while the review is unfinished.')
        final_args = dict(common, response='All requested synthetic checks are complete.',
                          previous_turn_id=turn['turn_id'], acknowledgment='delivered',
                          returned_files=[str(last_output)],
                          completion_observation={'status': 'completed',
                                                  'resolved_checks': ['Inspect remaining diagram']})
        with self.assertRaisesRegex(ValueError, 'Conversation reference differs'):
            self.hub.record_handoff_result(**{**final_args, 'conversation_ref': 'unrelated-muse-chat'})
        completed = self.hub.record_handoff_result(**final_args)['job']
        self.assertEqual(completed['state'], 'returned_via_handoff')
        self.assertEqual(completed['conversation_ref'], reference)
        self.assertEqual(completed['handoff_turns'][-1]['previous_answer_sha256'], turn['answer_sha256'])
        self.assertEqual(self.hub.result(self.project, job['id'])['answer'], final_args['response'])
        self.assertEqual(self.hub.result(self.project, job['id'], turn_id=turn['turn_id'])['answer'], partial_text)
        first_artifact = self.hub.attachment_files(self.project, job['id'], 'output', turn['turn_id'])
        final_artifact = self.hub.attachment_files(self.project, job['id'], 'output')
        self.assertEqual(Path(first_artifact['upload_paths'][0]).read_bytes(), first_bytes)
        self.assertEqual(Path(final_artifact['upload_paths'][0]).read_bytes(), last_output.read_bytes())
        self.assertNotEqual(first_artifact['upload_paths'], final_artifact['upload_paths'])
        reloaded = core.Hub(self.hub.state).result(self.project, job['id'])['job']
        self.assertEqual(reloaded['dispatch_mode'], 'manual_coordinator')
        self.assertFalse(reloaded['backend_model_verified'])
        self.fixture.launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
