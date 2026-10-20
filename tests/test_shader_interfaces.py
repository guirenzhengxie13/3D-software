"""Check the actual embedded GLSL ES 1.00 link interfaces.

This is a focused static regression check, not a real WebGL compiler or
browser-render test. It models stage precision defaults so that implicit
vertex-highp/fragment-mediump mismatches cannot be hidden by a WebGL mock.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATORS = (
    ROOT / "scripts" / "build_fusion_comparison.py",
    ROOT / "scripts" / "build_reconstruction_review.py",
)


@dataclass(frozen=True)
class Declaration:
    type: str
    precision: str | None
    array_length: str | None


def extract_shaders(path):
    """Read constant HTML and shader literals without executing a generator."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    html = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "HTML" for target in node.targets)
    )
    named_literals = re.findall(
        r"\bconst\s+(vertexShaderSource|fragmentShaderSource)\s*=\s*`([^`]*)`",
        html,
        flags=re.DOTALL,
    )
    if named_literals:
        if len(named_literals) != 2 or {name for name, _ in named_literals} != {
            "vertexShaderSource", "fragmentShaderSource"
        }:
            raise ValueError(f"Expected one named shader literal per stage in {path.name}")
        if any("${" in text for _, text in named_literals):
            raise ValueError("Dynamic template interpolation is unsupported by the static shader check")
        return {
            "VERTEX_SHADER" if name == "vertexShaderSource" else "FRAGMENT_SHADER": text
            for name, text in named_literals
        }
    pattern = re.compile(
        r"(?:compile|shader)\(\s*gl\.(VERTEX_SHADER|FRAGMENT_SHADER)\s*,\s*"
        r"('(?:[^'\\]|\\.)*')\s*\)"
    )
    found = [(stage, ast.literal_eval(literal)) for stage, literal in pattern.findall(html)]
    if len(found) != 2 or {stage for stage, _ in found} != {"VERTEX_SHADER", "FRAGMENT_SHADER"}:
        raise ValueError(f"Expected one literal shader per stage in {path.name}")
    return dict(found)


def top_level(source):
    """Discard comments and function/struct bodies, retaining declaration order."""
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
    depth = 0
    result = []
    for char in source:
        if char == "{":
            depth += 1
            result.append(" ")
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced GLSL braces")
            result.append(" ")
        else:
            result.append(char if depth == 0 else " ")
    if depth:
        raise ValueError("Unbalanced GLSL braces")
    return "".join(result)


def declarations(source, stage):
    # GLSL ES 1.00 specifies highp floats/ints in the vertex stage. The
    # fragment stage has mediump ints and no default float precision.
    defaults = {"float": "highp" if stage == "vertex" else None,
                "int": "highp" if stage == "vertex" else "mediump",
                "sampler2D": "lowp", "samplerCube": "lowp"}
    found = {"uniform": {}, "varying": {}, "attribute": {}}
    precision = re.compile(r"precision\s+(lowp|mediump|highp)\s+(float|int|sampler2D|samplerCube)\s*;")
    declaration = re.compile(
        r"(uniform|varying|attribute)\s+(?:(lowp|mediump|highp)\s+)?"
        r"(float|vec[234]|mat[234]|int|ivec[234]|bool|bvec[234]|sampler2D|samplerCube)\s+"
        r"([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*\])?\s*;"
    )
    for token in re.finditer(r"\b(?:precision|uniform|varying|attribute)\b[^;{}]*;", top_level(source)):
        text = token.group(0)
        if match := precision.fullmatch(text):
            defaults[match[2]] = match[1]
            continue
        match = declaration.fullmatch(text)
        if not match:
            raise ValueError(f"Unsupported interface declaration: {text}")
        storage, explicit, type_name, name, array_length = match.groups()
        if type_name == "float" or type_name.startswith(("vec", "mat")):
            family = "float"
        elif type_name == "int" or type_name.startswith("ivec"):
            family = "int"
        elif type_name.startswith("sampler"):
            family = type_name
        else:
            family = None
        effective = explicit or (defaults[family] if family else None)
        if family and effective is None:
            raise ValueError(f"No default {family} precision for {stage} {name}")
        if name in found[storage]:
            raise ValueError(f"Duplicate declaration of {name}")
        found[storage][name] = Declaration(type_name, effective, array_length)
    return found


def interface_errors(vertex, fragment):
    vertex = declarations(vertex, "vertex")
    fragment = declarations(fragment, "fragment")
    errors = []
    for name, value in fragment["varying"].items():
        if name not in vertex["varying"]:
            errors.append(f"varying {name} is missing from vertex shader")
        elif value != vertex["varying"][name]:
            errors.append(f"varying {name} differs: vertex={vertex['varying'][name]}, fragment={value}")
    for name in vertex["uniform"].keys() & fragment["uniform"].keys():
        if vertex["uniform"][name] != fragment["uniform"][name]:
            errors.append(f"uniform {name} differs: vertex={vertex['uniform'][name]}, fragment={fragment['uniform'][name]}")
    return errors


class ShaderInterfaceTests(unittest.TestCase):
    def test_web_studio_and_workbench_shader_interfaces_match(self):
        source=(ROOT/'web/landmark-workbench/app.js').read_text(encoding='utf-8')
        shaders={name:ast.literal_eval(literal) for name,literal in re.findall(r"const\s+(vertex|fragment)=('(?:[^'\\]|\\.)*')",source)}
        self.assertEqual(interface_errors(shaders['vertex'],shaders['fragment']),[])
        source=(ROOT/'web/studio/point_viewer.js').read_text(encoding='utf-8')
        shaders={name:ast.literal_eval(literal) for name,literal in re.findall(r"compile\(gl\.(VERTEX_SHADER|FRAGMENT_SHADER),('(?:[^'\\]|\\.)*')",source)}
        self.assertEqual(interface_errors(shaders['VERTEX_SHADER'],shaders['FRAGMENT_SHADER']),[])

    def test_actual_generator_link_interfaces_match(self):
        for path in GENERATORS:
            with self.subTest(generator=path.name):
                shaders = extract_shaders(path)
                self.assertEqual(interface_errors(shaders["VERTEX_SHADER"], shaders["FRAGMENT_SHADER"]), [])

    def test_actual_vertex_coordinates_keep_high_precision(self):
        for path in GENERATORS:
            with self.subTest(generator=path.name):
                vertex = declarations(extract_shaders(path)["VERTEX_SHADER"], "vertex")
                self.assertEqual(vertex["attribute"]["aPosition"], Declaration("vec3", "highp", None))
                self.assertEqual(vertex["uniform"]["uMVP"], Declaration("mat4", "highp", None))

    def test_original_implicit_uniform_and_varying_bug_is_detected(self):
        vertex = "uniform float uClassify;varying vec3 vColor;varying float vClass;void main(){}"
        fragment = "precision mediump float;uniform float uClassify;varying vec3 vColor;varying float vClass;void main(){}"
        errors = interface_errors(vertex, fragment)
        self.assertEqual(len(errors), 3)
        for name in ("uClassify", "vColor", "vClass"):
            self.assertTrue(any(name in error for error in errors))

    def test_removing_actual_shared_precision_reproduces_link_failure(self):
        for path in GENERATORS:
            with self.subTest(generator=path.name):
                shaders = extract_shaders(path)
                mutated = re.sub(
                    r"\b(uniform|varying)\s+mediump\s+", r"\1 ", shaders["VERTEX_SHADER"]
                )
                errors = interface_errors(mutated, shaders["FRAGMENT_SHADER"])
                self.assertTrue(errors, "Removing explicit precision must reintroduce the original mismatch")
                self.assertTrue(any("vColor" in error for error in errors))
                if path.name == "build_fusion_comparison.py":
                    for name in ("uClassify", "uOverride", "vClass"):
                        self.assertTrue(any(name in error for error in errors))

    def test_explicit_shared_precision_does_not_lower_position_precision(self):
        vertex = "attribute vec3 aPosition;uniform mat4 uMVP;uniform mediump float uClassify;varying mediump vec3 vColor;void main(){}"
        fragment = "precision mediump float;uniform mediump float uClassify;varying mediump vec3 vColor;void main(){}"
        self.assertEqual(interface_errors(vertex, fragment), [])
        parsed = declarations(vertex, "vertex")
        self.assertEqual(parsed["attribute"]["aPosition"].precision, "highp")
        self.assertEqual(parsed["uniform"]["uMVP"].precision, "highp")

    def test_uniform_type_and_array_length_must_match(self):
        vertex = "uniform mediump vec4 colors[2];void main(){}"
        for fragment in ("uniform mediump vec4 colors[3];void main(){}",
                         "uniform mediump vec3 colors[2];void main(){}"):
            with self.subTest(fragment=fragment):
                self.assertEqual(len(interface_errors(vertex, fragment)), 1)

    def test_missing_varying_and_fragment_default_are_rejected(self):
        self.assertTrue(interface_errors("void main(){}", "varying mediump vec3 absent;void main(){}"))
        with self.assertRaisesRegex(ValueError, "No default float precision"):
            declarations("uniform float noPrecision;void main(){}", "fragment")

    def test_comments_and_function_local_defaults_do_not_change_interfaces(self):
        source = "// uniform lowp vec3 notReal;\nuniform vec3 position;void main(){precision lowp float;}/*uniform vec3 fake;*/"
        parsed = declarations(source, "vertex")
        self.assertEqual(set(parsed["uniform"]), {"position"})
        self.assertEqual(parsed["uniform"]["position"].precision, "highp")


if __name__ == "__main__":
    unittest.main()
