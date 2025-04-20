# GitLab support for llm-fragments

This extension adds support for loading GitLab repositories and GitLab issues
as LLM fragments.

Forked from Simon Willison's llm-fragments-github
https://github.com/simonw/llm-fragments-github

---

## Usage

Use `-f gitlab:gitlab.example.com:user/project` to include every text file
from the specified GitLab repository.

Use `-f gitlab-issue:gitlab.example.com:user/project/issue/NUMBER` to include
a specific GitLab issue.

Example:

```bash
llm -f gitlab:gitlab.example.com:myuser/myproject 'summarize the repository'
```

```bash
llm -f gitlab-issue:gitlab.example.com:myuser/myproject/issue/15 'suggest fixes for this issue'
```

---

## Environment Variables

Set `GITLAB_TOKEN` to your GitLab personal access token for private repos and
increased API limits.

---

# Installation

Add the `llm_fragments_gitlab.py` module alongside your existing plugin
and register the new loaders as needed.
