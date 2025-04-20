from .loader import gitlab_loader, gitlab_issue_loader
import llm


@llm.hookimpl
def register_fragment_loaders(register):
    register("gitlab", gitlab_loader)
    register("gitlab-issue", gitlab_issue_loader)
