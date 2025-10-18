"""Configuration management for gitops-lite."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class StackConfig:
    """Configuration for a single stack (repo + cluster binding)."""

    name: str
    repo: str
    branch: str
    context: str | None = None
    namespace: str | None = None
    cache_path: str | None = None
    renderer_type: str | None = None
    renderer_kustomize_dir: str | None = None
    renderer_kustomize_build_args: list[str] | None = None
    # Legacy fields for backward compatibility (ignored)
    renderer_helm_chart: str | None = None
    renderer_helm_release_name: str | None = None
    renderer_helm_values_files: list[str] | None = None
    renderer_helm_set_values: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.cache_path:
            self.cache_path = str(get_config_dir() / "repos" / self.name)


@dataclass
class Config:
    """Global configuration for gitops-lite."""

    stacks: list[StackConfig] = field(default_factory=list)

    def add_stack(self, stack: StackConfig) -> None:
        """Add a stack to the configuration."""
        # Remove existing stack with same name
        self.stacks = [s for s in self.stacks if s.name != stack.name]
        self.stacks.append(stack)

    def remove_stack(self, name: str) -> bool:
        """Remove a stack from the configuration. Returns True if found and removed."""
        original_len = len(self.stacks)
        self.stacks = [s for s in self.stacks if s.name != name]
        return len(self.stacks) < original_len

    def get_stack(self, name: str) -> StackConfig | None:
        """Get a stack by name."""
        for stack in self.stacks:
            if stack.name == name:
                return stack
        return None


def get_config_dir() -> Path:
    """Get the gitops-lite configuration directory (~/.gitops-lite)."""
    config_dir = Path.home() / ".gitops-lite"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file() -> Path:
    """Get the configuration file path (~/.gitops-lite/config.yaml)."""
    return get_config_dir() / "config.yaml"


def load_config() -> Config:
    """Load configuration from file."""
    config_file = get_config_file()
    if not config_file.exists():
        return Config()

    with open(config_file, "r") as f:
        data = yaml.safe_load(f)

    if not data or "stacks" not in data:
        return Config()

    stacks = [StackConfig(**stack_data) for stack_data in data["stacks"]]
    return Config(stacks=stacks)


def save_config(config: Config) -> None:
    """Save configuration to file."""
    config_file = get_config_file()

    data = {
        "stacks": [
            {
                "name": s.name,
                "repo": s.repo,
                "branch": s.branch,
                "context": s.context,
                "namespace": s.namespace,
                "cache_path": s.cache_path,
                "renderer_type": s.renderer_type,
                "renderer_kustomize_dir": s.renderer_kustomize_dir,
                "renderer_kustomize_build_args": s.renderer_kustomize_build_args,
                "renderer_helm_chart": s.renderer_helm_chart,
                "renderer_helm_release_name": s.renderer_helm_release_name,
                "renderer_helm_values_files": s.renderer_helm_values_files,
                "renderer_helm_set_values": s.renderer_helm_set_values,
            }
            for s in config.stacks
        ]
    }

    with open(config_file, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def ensure_repos_dir() -> None:
    """Ensure the repos directory exists."""
    repos_dir = get_config_dir() / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
