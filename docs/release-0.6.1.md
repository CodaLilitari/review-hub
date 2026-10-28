# Review Hub 0.6.1 maintenance update

This maintenance update preserves the existing twenty-tool MCP/CLI interface and existing review records. New model-policy fields are optional for unconfigured installations.

- App model selection can retain an explicit standing primary/fallback policy. Conditional fallback requires fresh evidence about the exact primary control or an explicit failure of a request made with the primary selected. Generic menu text, history errors and evidence from an earlier catalog observation do not qualify. An unrelated catalog change does not require another permission question when an authorized standing choice applies.
- Six narrow SQLite compatibility checks prevent older running clients from dropping a configured policy, writing an unclassified choice or consuming a policy-unbound choice. These checks validate local records, not provider availability. Current primary choices, deliberate policy replacement and existing review-result recording remain supported.
- Grok Bot handoffs use a verified background browser route and preserve the intended saved Bot thread or project anchor. There is no automatic desktop fallback or verified complete headless Bot adapter. Grok Bot, Grok Build and ordinary Grok chat remain distinct. Usage evidence must match the actual account, plan and applicable product meter.
- Claude Code result handling preserves explicit tool/output limits and bounded partial answers without treating them as completed reviews. The subscription-only helper excludes credit-dependent model choices and unresolved aliases whose included-usage eligibility is unverified.
- Helper prompt transport, attachment handling, media-review guidance and synthetic regressions include the corrections accumulated since 0.6.0.

## Edition boundary

The personalized private distribution and neutral public distribution keep separate Git histories. The public package has no personal seed, configured collaborator names, account/model preferences, helper paths, private conversations, credentials, usage records or review databases. Its example helper configuration is not a working adapter configuration. Existing users retain their own local identity, model choices and state.

## Updating

Keep the existing state directory. Current code installs the model-store compatibility checks without deleting existing rows. A configured standing policy is needed before its selection restrictions apply; updating source alone does not invent a policy.

An already running MCP process retains its imported code and schema. Use current CLI code for new policy operations and reconnect that client when its active work is safely reconciled. Do not indiscriminately terminate other clients or provider jobs. The database checks protect existing configured policies from legacy writes; they do not refresh cached route descriptions.

Helper source changes require reviewing the new bytes and updating the corresponding local SHA-256 pins. The public example intentionally supplies no usable pins or personal runtime paths.

## Validation scope

The regression suite is offline and uses synthetic temporary states. It covers policy evidence, stale-client compatibility, rollback, handoff/result continuity and route separation. It does not establish current login, included usage, provider billing behavior, backend model identity or end-to-end provider completion.

Run from the intended checkout with that checkout's package selected:

```text
python -B -m unittest discover -s tests -q
```

Keep test artifacts outside Git. Private and public publication receipts should identify their separate commits and independently verify each mirror. This update does not add a software license or change repository visibility.
