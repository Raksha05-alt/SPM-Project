# Test case documentation

[Test_Cases_All_Sprints.xlsx](Test_Cases_All_Sprints.xlsx) is the current complete case register: 338 records across the 62 imported US stories. Each case contains preconditions, steps, data, expected and recorded results, exact test references and a peer-review table. Its Index links to each case and Jira; ID Mapping resolves older worksheet IDs.

[story-test-index.csv](story-test-index.csv) is a compact navigation index from US story to workbook cases and source test files. It is not a second editable case specification. Related-story E2E groups can share executions; do not sum overlapping group counts.

The other CSVs retain the implementation and integration records produced during earlier story phases. Their original SCRUM/G identifiers are historical. In the imported workspace, SCRUM-n maps to US-n; older specification tags such as US-01.1 are a different naming scheme and must not be mapped by their number alone. QA-coverage-regressions.csv includes an explicit current workbook ID.

The current register contains 304 passing automated AC cases, 12 passing E2E groups and six passing regression groups. Two superseded automatic-assignment criteria and 14 historical manual records remain distinct. Four of those historical records have no execution result; the two superseded criteria are also Not Executed.

Assigned reviewers are allocations, not proof of completed peer review. The packaged workbook preserves actual review fields and does not substitute simulated comments or statuses. Keep simulation reference workbooks outside this evidence package.

See [the testing guide](../testing/README.md) for commands, execution evidence, coverage and remaining checks.
