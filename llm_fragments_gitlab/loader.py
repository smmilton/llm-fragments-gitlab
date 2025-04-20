from typing import List, Tuple
import httpx
import llm
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse


@llm.hookimpl
def register_fragment_loaders(register):
#    register("github", github_loader)
#    register("issue", github_issue_loader)
    register("gitlab", gitlab_loader)
    register("gitlab-issue", gitlab_issue_loader)


#def github_loader(argument: str) -> List[llm.Fragment]:
    # Original github_loader unchanged here, assumed imported or copied
#    raise NotImplementedError("github_loader should be imported or defined elsewhere")


#def github_issue_loader(argument: str) -> llm.Fragment:
    # Original github_issue_loader unchanged here, assumed imported or copied
#    raise NotImplementedError("github_issue_loader should be imported or defined elsewhere")


def gitlab_loader(argument: str) -> List[llm.Fragment]:
    """
    Load files from a GitLab repository as fragments.

    Argument is gitlab.fqdn.com:user/project or full https URL.
    """
    # Normalize SSH repository URL
    if re.match(r"^[^:/]+:[^/]+/[^/]+$", argument):
        host, path = argument.split(":", 1)
        # Compose SSH URL: git@host:path.git
        repo_url = f"git@{host}:{path}.git"
        arg_id = f"{host}/{path}"
    elif argument.startswith("http://") or argument.startswith("https://"):
        p = urllib.parse.urlparse(argument)
        # Convert https URL to ssh URL
        host = p.netloc
        path = p.path.lstrip("/").removesuffix(".git")
        repo_url = f"git@{host}:{path}.git"
        arg_id = f"{host}/{path}"
    else:
        raise ValueError(f"Invalid GitLab argument: {argument}")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", "--filter=blob:none", repo_url, temp_dir],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "checkout", "HEAD", "--", "."],
                check=True,
                capture_output=True,
                text=True,
                cwd=temp_dir,
            )

            git_dir = pathlib.Path(temp_dir) / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir)

            repo_path = pathlib.Path(temp_dir)
            fragments = []
            for file_path in repo_path.glob("**/*"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        relative_path = file_path.relative_to(repo_path)
                        fragments.append(llm.Fragment(content, f"{arg_id}/{relative_path}"))
                    except UnicodeDecodeError:
                        continue
            return fragments

        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to clone repository {repo_url}: {e.stderr}")
        except Exception as e:
            raise ValueError(f"Error processing repository {repo_url}: {str(e)}")

def gitlab_issue_loader(argument: str) -> llm.Fragment:
    """
    Fetch GitLab issue and comments as Markdown.

    Argument is gitlab.fqdn.com:user/project/issue/NUMBER or
    user/project/issue/NUMBER
    """
    try:
        host, user, project, number = _parse_gitlab_issue_argument(argument)
    except ValueError as ex:
        raise ValueError(
            "GitLab issue fragments must be in the form gitlab.fqdn.com:user/project/issue/NUMBER "
            "or user/project/issue/NUMBER"
            f" – received {argument!r}"
        ) from ex

    client = _gitlab_client(host)

    # URL encode project path e.g. user/project -> user%2Fproject
    project_id = urllib.parse.quote_plus(f"{user}/{project}")

    issue_api = f"https://{host}/api/v4/projects/{project_id}/issues/{number}"

    issue_resp = client.get(issue_api)
    _raise_for_status(issue_resp, issue_api)
    issue = issue_resp.json()

    # Comments in GitLab are called notes, endpoint:
    notes_api = f"https://{host}/api/v4/projects/{project_id}/issues/{number}/notes?per_page=100"

    comments = _get_all_pages(client, notes_api)

    markdown = _gitlab_to_markdown(issue, comments)

    return llm.Fragment(
        markdown,
        source=f"https://{host}/{user}/{project}/-/issues/{number}",
    )


def _parse_gitlab_issue_argument(arg: str) -> Tuple[str, str, str, int]:
    """
    Returns (host, user, project, number) or raises ValueError
    Possible forms:
    - gitlab.fqdn.com:user/project/issue/NUMBER
    - user/project/issue/NUMBER (assume gitlab.com)
    """
    if ":" in arg:
        host_part, rest = arg.split(":", 1)
        parts = rest.strip("/").split("/")
        if len(parts) == 4 and parts[2] in ("issue", "issues"):
            user, project, _, number_str = parts
            return host_part, user, project, int(number_str)
        else:
            raise ValueError("Invalid GitLab issue argument")
    else:
        parts = arg.strip("/").split("/")
        if len(parts) == 4 and parts[2] in ("issue", "issues"):
            user, project, _, number_str = parts
            return "gitlab.com", user, project, int(number_str)
        else:
            raise ValueError("Invalid GitLab issue argument")


def _gitlab_client(host: str) -> httpx.Client:
    headers = {"Accept": "application/json"}
    token = os.getenv("GITLAB_TOKEN")
    if token:
        headers["PRIVATE-TOKEN"] = token
    return httpx.Client(headers=headers, timeout=30.0, follow_redirects=True)


def _raise_for_status(resp: httpx.Response, url: str) -> None:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as ex:
        raise ValueError(
            f"API request failed [{resp.status_code}] for {url}"
        ) from ex


def _get_all_pages(client: httpx.Client, url: str) -> List[dict]:
    items: List[dict] = []
    while url:
        resp = client.get(url)
        _raise_for_status(resp, url)
        items.extend(resp.json())

        # Link header pagination
        url = None
        link = resp.headers.get("Link")
        if link:
            for part in link.split(","):
                if part.endswith('rel="next"'):
                    url = part[part.find("<") + 1 : part.find(">")]
                    break
    return items


def _gitlab_to_markdown(issue: dict, comments: List[dict]) -> str:
    md: List[str] = []
    md.append(f"# {issue['title']}\n")
    if "author" in issue and issue["author"] and "username" in issue["author"]:
        md.append(f"*Posted by @{issue['author']['username']}*\n")
    if issue.get("description"):
        md.append(issue["description"] + "\n")

    if comments:
        md.append("---\n")
        for c in comments:
            if c.get("system") and c["system"]:
                # system notes can be skipped or handled differently
                continue
            if "author" in c and c["author"] and "username" in c["author"]:
                md.append(f"### Comment by @{c['author']['username']}\n")
            else:
                md.append("### Comment\n")
            if c.get("body"):
                md.append(c["body"] + "\n")
            md.append("---\n")

    return "\n".join(md).rstrip() + "\n"
