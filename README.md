# KENSEI Agent

KENSEI is Sahil Saghir's private, persistent personal AI agent, built on Hermes Agent and running on Sahil's own Linux VPS.

The goal is simple: turn Sahil's scattered daily ops into one reliable command layer. Email triage, research, content drafts, coding support, memory recall and personal admin should all flow through one agent that gets sharper over time.

## What KENSEI is supposed to become

KENSEI is the orchestrator. It receives work through CLI, Telegram, Discord and the Hermes browser dashboard, then routes tasks to specialist workflows or subagents:

- Research: daily and on-demand intelligence for AI, devtools, Hermes, Claude Code and other topics worth Sahil's attention.
- Mailbox: triage across Gmail and Outlook accounts, surfacing only what actually needs action.
- Content: copy/paste-ready drafts for Plenishd, MatchdayMaestro and Sahil's personal brand.
- Coding: repository work, code review, implementation support, tests and PR assistance.
- General assist: planning, reminders, personal admin and ad-hoc execution.

It is designed to be self-hosted, private by default and approval-gated for destructive or external actions.

## Current North Star MVP

The MVP is not a flashy agent swarm. That would be bullshit at this stage.

The useful version of KENSEI is done when it can reliably:

1. Produce a useful mailbox digest across all connected inboxes.
2. Produce a useful research digest with sources and one practical recommendation.
3. Run through the Hermes dashboard from browser and phone via Tailscale or tunnel.
4. Draft usable text content for MatchdayMaestro, Plenishd or Sahil's personal channels.
5. Recall prior context through the current memory and session-search stack.
6. Stay operationally boring: gateway connected, heartbeat healthy, cron jobs working, backups and token checks under control.

## Architecture

At a high level:

- Command Center: browser and mobile access through `hermes dashboard`.
- Gateway: Telegram, Discord, CLI and eventually email.
- Cron Scheduler: autonomous daily and weekly workflows.
- Orchestrator: KENSEI main agent.
- Specialist agents: Research, Mailbox, Content, Coding and General Assist.
- Shared infrastructure: skills, MCP integrations, memory, search, audit logs and backups.

## Integrations

KENSEI is expected to use:

- Gmail and Google Workspace MCP.
- Outlook / Microsoft Graph MCP.
- GitHub token and future GitHub MCP workflows.
- Hermes skills and session search.
- Mem0 now, with Hindsight as a possible post-MVP local memory upgrade.
- Postiz, Composio, richer subagent profiles and voice calls later, only after the MVP is reliable.

## Operating principles

- Private first. Data stays on Sahil's infrastructure unless explicitly routed elsewhere.
- Approval-gated. No sending emails, posting content, spending money or destructive changes without confirmation.
- Useful before clever. Daily value beats fancy architecture.
- Skills compound. Successful workflows should become reusable skills.
- Auditability matters. Important actions should leave a trail.

## Source of truth

This README is a lightweight public-facing summary for the private repo.

The full planning source of truth is Sahil's local `NorthStar.md` document.