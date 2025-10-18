"""Parser for kubectl diff unified diff output."""

import re
from dataclasses import dataclass


@dataclass
class DiffItem:
    """Represents a single resource diff."""

    state: str  # ADDED | CHANGED | DELETED
    gvk: str  # Group/Version/Kind
    namespace: str | None
    name: str
    snippet: str  # Excerpt of the diff


def parse_unified(diff_text: str) -> list[DiffItem]:
    """Parse kubectl diff unified diff output into DiffItem objects.

    kubectl diff produces unified diffs with headers like:
    diff -u -N /tmp/LIVE-123/apps.v1.Deployment.default.nginx ...

    The diff format:
    - Lines starting with '+++' indicate new/changed resources
    - Lines starting with '---' indicate old/deleted resources
    - If only '+++' exists (no '---'): resource is ADDED
    - If only '---' exists (no '+++'): resource is DELETED
    - If both exist: resource is CHANGED
    """
    items: list[DiffItem] = []

    # Split by diff headers (lines starting with 'diff ')
    diff_blocks = re.split(r'^diff ', diff_text, flags=re.MULTILINE)

    for block in diff_blocks:
        if not block.strip():
            continue

        # Parse the diff header to extract resource info
        item = _parse_diff_block(block)
        if item:
            items.append(item)

    return items


def _parse_diff_block(block: str) -> DiffItem | None:
    """Parse a single diff block into a DiffItem."""
    lines = block.split('\n')

    # First line should contain the diff header
    # Format: -u -N /tmp/LIVE-123/apps.v1.Deployment.default.nginx ...
    if not lines:
        return None

    header_line = "diff " + lines[0]

    # Extract resource info from the path
    # Path format: /tmp/LIVE-xxx/{gvk}.{namespace}.{name}
    # GVK can be v1.Service (2 parts) or apps.v1.Deployment (3 parts)
    # or: /tmp/LIVE-xxx/{gvk}..{name} (for cluster-scoped resources)
    match = re.search(r'/([^/\.]+\.[^/\.]+(?:\.[^/\.]+)?)\.([^/]+)\.([^/\s]+)', header_line)
    if not match:
        # Try cluster-scoped format (no namespace)
        match = re.search(r'/([^/\.]+\.[^/\.]+(?:\.[^/\.]+)?)\.\.([^/\s]+)', header_line)
        if not match:
            return None
        gvk = match.group(1)
        namespace = None
        name = match.group(2)
    else:
        gvk = match.group(1)
        namespace = match.group(2)
        name = match.group(3)

    # Determine state by looking for --- and +++ markers
    has_old = any(line.startswith('---') for line in lines)
    has_new = any(line.startswith('+++') for line in lines)

    if has_new and not has_old:
        state = "ADDED"
    elif has_old and not has_new:
        state = "DELETED"
    elif has_old and has_new:
        state = "CHANGED"
    else:
        # No markers found, skip this block
        return None

    # Extract a snippet (first 50 lines of actual diff content)
    snippet_lines = []
    in_diff = False
    for line in lines:
        if line.startswith('@@'):
            in_diff = True
            continue
        if in_diff and (line.startswith('+') or line.startswith('-') or line.startswith(' ')):
            snippet_lines.append(line)
            if len(snippet_lines) >= 50:
                break

    snippet = '\n'.join(snippet_lines) if snippet_lines else "(no diff content)"

    # Refine state detection: if marked as CHANGED but all content lines are + or -,
    # it's actually an ADD or DELETE (e.g., resource rename in Kustomize)
    if state == "CHANGED" and snippet_lines:
        content_lines = [l for l in snippet_lines if l.startswith(('+', '-'))]
        if content_lines:
            plus_lines = [l for l in content_lines if l.startswith('+')]
            minus_lines = [l for l in content_lines if l.startswith('-')]

            # If 100% of content is additions, it's really an ADD
            if plus_lines and not minus_lines:
                state = "ADDED"
            # If 100% of content is deletions, it's really a DELETE
            elif minus_lines and not plus_lines:
                state = "DELETED"

    return DiffItem(
        state=state,
        gvk=gvk,
        namespace=namespace,
        name=name,
        snippet=snippet,
    )


def format_diff_items(items: list[DiffItem]) -> str:
    """Format DiffItem list as human-readable text."""
    if not items:
        return "No changes detected"

    output = []
    for item in items:
        ns_str = f" (namespace: {item.namespace})" if item.namespace else " (cluster-scoped)"
        output.append(f"[{item.state}] {item.gvk}/{item.name}{ns_str}")

    return '\n'.join(output)


def count_by_state(items: list[DiffItem]) -> dict[str, int]:
    """Count items by state (ADDED, CHANGED, DELETED)."""
    counts = {"ADDED": 0, "CHANGED": 0, "DELETED": 0}
    for item in items:
        if item.state in counts:
            counts[item.state] += 1
    return counts


def filter_metadata_noise(snippet: str) -> str:
    """Filter out Kubernetes metadata fields that are just noise in diffs.

    These fields change automatically and aren't meaningful to users:
    - generation (increments on spec changes)
    - resourceVersion (changes on every update)
    - uid (set once on creation)
    - creationTimestamp (set once on creation)
    - selfLink (deprecated)
    - managedFields (server-side apply metadata)
    - kubectl.kubernetes.io/last-applied-configuration (client-side apply annotation)
    - deployment.kubernetes.io/revision (deployment revision number)
    """
    if not snippet or snippet == "(no diff content)":
        return snippet

    # List of metadata fields to ignore (regex patterns)
    # Matches both changed lines (+ or -) and context lines (space)
    noise_patterns = [
        r'^\s*[-+ ]?\s*generation:\s*\d+\s*$',
        r'^\s*[-+ ]?\s*resourceVersion:\s*["\']?\w+["\']?\s*$',
        r'^\s*[-+ ]?\s*uid:\s*[a-f0-9-]+\s*$',
        r'^\s*[-+ ]?\s*creationTimestamp:\s*.+$',
        r'^\s*[-+ ]?\s*selfLink:\s*.+$',
        r'^\s*[-+ ]?\s*kubectl\.kubernetes\.io/last-applied-configuration:\s*.+$',
        r'^\s*[-+ ]?\s*deployment\.kubernetes\.io/revision:\s*.+$',
    ]

    # Also filter managedFields blocks (can be multiple lines)
    lines = snippet.split('\n')
    filtered_lines = []
    skip_managed_fields = False
    in_metadata_section = False

    for line in lines:
        # Track if we're in metadata section
        if re.match(r'^\s*[-+ ]?\s*metadata:', line):
            in_metadata_section = True
        elif in_metadata_section and re.match(r'^\s*[-+ ]?\s*\w+:', line):
            # Exiting metadata section (new top-level field like spec:, status:)
            in_metadata_section = False

        # Check if we're entering a managedFields block
        if re.match(r'^\s*[-+ ]?\s*managedFields:', line):
            skip_managed_fields = True
            continue

        # Check if we're exiting managedFields (dedent to same or less level)
        if skip_managed_fields:
            # If line starts with less indentation or is a new field at metadata level, exit
            if re.match(r'^\s*[-+ ]?\s*\w+:', line) and not line.strip().startswith(('- ', '+ ')):
                skip_managed_fields = False
            else:
                continue

        # Check if line matches any noise pattern
        is_noise = any(re.match(pattern, line) for pattern in noise_patterns)

        if not is_noise:
            filtered_lines.append(line)

    # If all lines were filtered out, return a message
    filtered_snippet = '\n'.join(filtered_lines)
    if not filtered_snippet.strip():
        return "(only metadata changes)"

    return filtered_snippet
