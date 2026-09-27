"""Map legacy package names onto :mod:`agent_handoff` without copying modules.

``import handoff.engine`` and ``import session_distill.engine`` resolve to the
same module object as ``import agent_handoff.engine``.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from pathlib import Path
from typing import Dict, Optional


class _AliasLoader(importlib.abc.Loader):
    """Load the real module and publish it under the legacy name."""

    def __init__(self, real_name: str) -> None:
        self.real_name = real_name

    def create_module(self, spec: importlib.machinery.ModuleSpec):  # noqa: ANN201
        module = importlib.import_module(self.real_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module: object) -> None:
        return None


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``alias.<submodule>`` to ``target.<submodule>``."""

    def __init__(self) -> None:
        self.aliases: Dict[str, str] = {}

    def find_spec(
        self,
        fullname: str,
        path: Optional[list[str]],
        target: object = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        real_name = self._real_name(fullname)
        if real_name is None:
            return None
        parent_name, _, child = real_name.rpartition(".")
        if not parent_name or not child:
            return None
        parent = importlib.import_module(parent_name)
        parent_path = list(getattr(parent, "__path__", []))
        origin: Optional[Path] = None
        is_package = False
        for entry in parent_path:
            base = Path(entry)
            module_file = base / f"{child}.py"
            package_init = base / child / "__init__.py"
            if module_file.is_file():
                origin = module_file
                is_package = False
                break
            if package_init.is_file():
                origin = package_init
                is_package = True
                break
        if origin is None:
            return None
        spec = importlib.machinery.ModuleSpec(
            fullname,
            _AliasLoader(real_name),
            origin=str(origin),
            is_package=is_package,
        )
        if is_package:
            # Child imports still go through this finder (it sits at the front
            # of meta_path). An empty path keeps PathFinder from loading a
            # second copy of the same file under the legacy name.
            spec.submodule_search_locations = []
        return spec

    def _real_name(self, fullname: str) -> Optional[str]:
        for alias, target in self.aliases.items():
            prefix = alias + "."
            if fullname.startswith(prefix):
                return target + fullname[len(alias) :]
        return None


_FINDER: Optional[_AliasFinder] = None


def install_alias(alias: str, target: str = "agent_handoff") -> None:
    """Register ``alias.*`` as a view of ``target.*``.

    The top-level package itself stays a real shim module so
    ``from alias import *`` can re-export the public API.
    """

    global _FINDER
    if _FINDER is None:
        _FINDER = _AliasFinder()
        sys.meta_path.insert(0, _FINDER)
    _FINDER.aliases[alias] = target
