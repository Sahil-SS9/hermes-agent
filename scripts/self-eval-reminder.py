#!/usr/bin/env python3
"""Weekly self-eval reminder — prompts agents to log their self-evaluations."""
import datetime as dt

TZ = dt.timezone(dt.timedelta(hours=1))
now = dt.datetime.now(TZ)

print("🔄 <b>Self-Eval Reminder</b> · " + now.strftime("%d/%m/%y · %H:%M:%S"))
print()
print("It's Friday — time for this week's self-evaluation.")
print()
print("<b>Who should eval this week</b>")
print("• <b>Tier 2 (rolling):</b> Check the Logboard for this week's rotation")
print("• <b>Tier 1 (flagged):</b> Any agent tagged Refinement-Needed since last eval")
print()
print("Use the template at <code>/home/kensei/.hermes/governance/self-eval-schema.md</code>")
print()
print("Save evels to <code>/home/kensei/.hermes/governance/logboard/</code>")
print("as <code>self-eval-{agent}-{YYYY-MM-DD}.md</code>")
print()
print("<blockquote expandable><b>Eval protocol</b>")
print("1. Agent writes self-eval using the schema template")
print("2. Saved to Logboard as a markdown file")
print("3. Denji-reviewer reads and categorises: keep / refine / escalate")
print("4. Refinement-Needed entries get Tier 1 review within the week")
print("5. Profile changes go on the Profile Change Ledger with a 2-week follow-up")
print("</blockquote>")
