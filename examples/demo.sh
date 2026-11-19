#!/bin/sh
# A bad morning for a support assistant, end to end. Every time is passed with --at so the run is reproducible.
# Usage: sh examples/demo.sh   (from the repository root; writes /tmp/incident-demo.json)
set -e
DB=/tmp/incident-demo.json
rm -f "$DB"
P="python -m incident_log --db $DB"
$P --at 2026-03-02T08:00 open INC-101 "Assistant quoted a refund policy that does not exist" \
  --impact 5 --likelihood 4 --detectability 2 --category hallucination --system support-assistant \
  --occurred 2026-03-02T06:10 --detected-by customer --customers 14 --owner maria \
  --impact-text "14 customers were promised refunds the policy does not allow"
$P --at 2026-03-02T08:12 ack INC-101 --by maria
$P --at 2026-03-02T08:55 mitigate INC-101 --note "Retrieval pinned to the current policy document"
$P --at 2026-03-02T11:30 open INC-102 "Support transcripts logged with card numbers" \
  --impact 4 --likelihood 3 --detectability 2 --category pii_exposure --system support-assistant \
  --detected-by audit --personal-data --owner dev
$P --at 2026-03-02T11:35 track INC-102 gdpr_33
$P --at 2026-03-02T11:20 resolve INC-101 --cause "The index still held the 2024 policy, which the model preferred" --fix "Re-indexed and added a freshness filter"
echo
echo "--- two days later: INC-102 was never picked up ---"
$P --at 2026-03-04T12:00 status || true
echo
echo "--- what INC-101's postmortem still lacks ---"
$P --at 2026-03-04T12:00 gaps INC-101 || true
