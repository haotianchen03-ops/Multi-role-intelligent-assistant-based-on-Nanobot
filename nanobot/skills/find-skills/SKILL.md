---
name: find-skills
description: Search and discover skills from the open agent skills ecosystem. Use when user asks "find a skill for X", "is there a skill for X", "search for skills", "browse skills", "install a skill", or wants to extend agent capabilities with specialized tools/workflows. Also use when user mentions a domain (design, testing, deployment, etc.) where an existing skill might help.
---

# Find Skills

This skill helps discover and install skills from the open agent skills ecosystem.

## When to Use This Skill

Use this skill when the user:
- Asks "how do I do X" where X might be a common task with an existing skill
- Says "find a skill for X" or "is there a skill for X"
- Asks "can you do X" where X is a specialized capability
- Expresses interest in extending agent capabilities
- Wants to search for tools, templates, or workflows
- Mentions they wish they had help with a specific domain (design, testing, deployment, etc.)
- Asks to "search/browse/install skills"

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

### Key Commands

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills add <owner/repo@skill>` - Install a skill from GitHub or other sources
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

Browse skills at: https://skills.sh/

## How to Help Users Find Skills

### Step 1: Understand What They Need

Identify:
- The domain (e.g., React, testing, design, deployment)
- The specific task (e.g., writing tests, creating animations, reviewing PRs)
- Whether this is a common enough task that a skill likely exists

### Step 2: Search for Skills

Run the find command:
```
npx skills find [query]
```

Examples:
- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

### Step 3: Verify Quality Before Recommending

Check:
- Install count — Prefer skills with 1K+ installs. Be cautious with anything under 100.
- Source reputation — Official sources (vercel-labs, anthropics, microsoft) are more trustworthy.
- GitHub stars — Check the source repository.

### Step 4: Present Options to User

When finding relevant skills, present:
- The skill name and what it does
- The install count and source
- The install command
- A link to learn more at skills.sh

Example response:
```
I found a skill that might help! The "react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.
(185K installs)

To install it:
npx skills add vercel-labs/agent-skills@react-best-practices

Learn more: https://skills.sh/vercel-labs/agent-skills/react-best-practices
```

### Step 5: Offer to Install

If the user wants to proceed:
```
npx skills add <owner/repo@skill> -g -y
```
The `-g` flag installs globally (user-level) and `-y` skips confirmation.

## Common Skill Categories

| Category | Example Queries |
|----------|-----------------|
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing | testing, jest, playwright, e2e |
| DevOps | deploy, docker, kubernetes, ci-cd |
| Documentation | docs, readme, changelog, api-docs |
| Code Quality | review, lint, refactor, best-practices |
| Design | ui, ux, design-system, accessibility |
| Productivity | workflow, automation, git |

## Tips for Effective Searches

- Use specific keywords: "react testing" is better than just "testing"
- Try alternative terms: If "deploy" doesn't work, try "deployment" or "ci-cd"
- Check popular sources: Many skills come from vercel-labs/agent-skills

## When No Skills Are Found

If no relevant skills exist:
- Acknowledge that no existing skill was found
- Offer to help with the task directly using general capabilities
- Suggest creating their own skill with the skill-creator skill

Example:
```
I searched for skills related to "xyz" but didn't find any matches.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill
using the skill-creator skill.
```
