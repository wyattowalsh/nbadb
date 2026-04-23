---
title: Customizing the Development Environment for GitHub Copilot Cloud Agent
kind: raw-source
status: captured
source_url: https://docs.github.com/en/copilot/customizing-copilot/customizing-the-development-environment-for-copilot-coding-agent
captured_on: 2026-04-14
capture_type: webfetch-markdown-summary
why_it_matters: Documents how Copilot cloud agent runs inside a GitHub Actions-backed ephemeral environment and how repositories can customize tools, runners, networking, and setup behavior.
---

## Source Record

- Source URL: `https://docs.github.com/en/copilot/customizing-copilot/customizing-the-development-environment-for-copilot-coding-agent`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page is the clearest first-party description of how Copilot cloud agent executes work. It explains the `copilot-setup-steps.yml` contract, what parts of the job are configurable, which runner types are supported, and how to handle environment variables, firewall behavior, LFS, and network access.

## Key Excerpts

> "While working on a task, Copilot has access to its own ephemeral development environment, powered by GitHub Actions"

> You can customize the environment with a workflow file named `copilot-setup-steps.yml`, and the job "MUST be called `copilot-setup-steps` or it will not be picked up by Copilot."

> Only a limited set of job settings are supported: `steps`, `permissions`, `runs-on`, `services`, `snapshot`, and `timeout-minutes`.

> Copilot cloud agent is only compatible with `Ubuntu x64 Linux` and `Windows 64-bit` runners, and self-hosted runner usage should be constrained with explicit network controls.

## Capture Notes

- The page frames Copilot cloud agent as a specialized GitHub Actions workload with a narrow, explicit customization surface.
- The setup workflow doubles as a normal Actions workflow, which gives repositories a built-in validation path for agent environment changes.
- Security posture is a recurring theme: least-privilege permissions, restricted firewall behavior, controlled domains, and caution around self-hosted runners.
