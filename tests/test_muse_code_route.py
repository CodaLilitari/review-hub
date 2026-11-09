"""Muse Code is a separate bounded CLI route, never a consumer-chat alias."""
import json
import unittest
import test_core
from coda_review_hub import core
from coda_review_hub.capabilities import route_capabilities


class MuseRouteTests(unittest.TestCase):
    setUp = test_core.HubTests.setUp
    write_pins = test_core.HubTests.write_pins

    def test_muse_cli_and_consumer_routes_remain_separate(self):
        routes = {row['provider']: row for row in self.hub.routes()['routes']}
        self.assertEqual(routes['muse-code']['transport'], 'cli')
        self.assertEqual(routes['muse-code']['label'], 'Muse Code CLI')
        self.assertFalse(routes['muse-code']['live_ready'])
        self.assertIsNone(routes['muse-code']['collaborator_name'])
        self.assertEqual(routes['meta-muse']['transport'], 'coordinator_handoff')
        self.assertNotIn('meta-muse', core.AUTO)
        self.assertFalse(route_capabilities('muse-code')['session_resume'])

    def test_new_route_does_not_silently_override_existing_personal_alias(self):
        path = self.hub.identity.path
        profile = json.loads(path.read_text())
        profile['aliases']['muse-code'] = 'meta-muse'
        path.write_text(json.dumps(profile))
        self.assertEqual(self.hub.identity.read()['alias_conflicts']['muse-code']['previous_target'], 'meta-muse')
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.hub.identity.resolve_provider('muse-code')


if __name__ == '__main__':
    unittest.main()
