from unittest.mock import MagicMock


def make_comment(body, login="mozilla-blender[bot]", created_at=None):
    """Build a mock GitHub comment with .body, .user.login, and .created_at."""
    c = MagicMock()
    c.user.login = login
    c.body = body
    c.created_at = created_at
    return c


def make_review(login, state="APPROVED", submitted_at=None):
    """Build a mock PR review with .user.login, .state, and .submitted_at."""
    r = MagicMock()
    r.user.login = login
    r.state = state
    r.submitted_at = submitted_at
    return r


def make_commit(message, date=None):
    """Build a mock commit with .commit.message and optional .commit.committer.date."""
    c = MagicMock()
    c.commit.message = message
    if date is not None:
        c.commit.committer.date = date
    return c


def make_branch(name):
    """Build a mock branch object with .name."""
    b = MagicMock()
    b.name = name
    return b


def make_tag(name):
    """Build a mock git tag object with .name."""
    t = MagicMock()
    t.name = name
    return t


def make_issue(number, title="Test issue", labels=None, assignees=None, is_pr=False):
    """Build a mock GitHub issue with .number, .title, .labels, .assignees."""
    i = MagicMock()
    i.number = number
    i.title = title
    i.pull_request = MagicMock() if is_pr else None

    mock_labels = []
    for name in (labels or []):
        lbl = MagicMock()
        lbl.name = name
        mock_labels.append(lbl)
    i.labels = mock_labels
    i.assignees = list(assignees or [])
    return i
