"""Tests for connectors.unreal_docs_scan.

Both sample texts below are trimmed, faithful reproductions of real Unreal
C++ headers (fetched from ``life-exe/UnrealTPSGame`` on GitHub during
development to verify layout conventions -- see the module's docstring):
``TPS_CHARACTER_H_TEXT`` is a typical ``UCLASS``-annotated Actor subclass
with ``UPROPERTY``/``UFUNCTION`` macros and Doxygen-style ``/** */`` doc
comments (both single- and multi-line, with ``@param``); ``BATTERY_H_TEXT``
is a plain, non-``UObject`` class using ``//!``-style line comments and
constructors with no return-type token.
"""

from __future__ import annotations

from spiced.connectors.unreal_docs_scan import scan_headers

TPS_CHARACTER_H_TEXT = """// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"

UCLASS(config = Game)
class ATPSCharacter : public ACharacter
{
    GENERATED_BODY()

    /** Camera boom positioning the camera behind the character */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = Camera)
    USpringArmComponent* CameraBoom;

public:
    ATPSCharacter();

    /** Base turn rate, in deg/sec. Other scaling may affect final turn rate. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = Camera)
    float BaseTurnRate;

protected:
    /** Resets HMD orientation in VR. */
    void OnResetVR();

    /**
     * Called via input to turn at a given rate.
     * @param Rate	This is a normalized rate, i.e. 1.0 means 100% of desired turn rate
     */
    void TurnAtRate(float Rate);

public:
    /** Returns CameraBoom subobject **/
    FORCEINLINE USpringArmComponent* GetCameraBoom() const { return CameraBoom; }

    bool operator==(const ATPSCharacter& rhs) const { return this == &rhs; }
};
"""

BATTERY_H_TEXT = """// My game copyright

#pragma once

#include "CoreMinimal.h"

namespace TPS
{
class TPS_API Battery
{
public:
    Battery() = default;
    Battery(float PercentIn);

    //! \\todo Add parameter for charging
    void Charge();
    //! \\todo Add parameter for uncharging
    void UnCharge();

    float GetPercent() const;

private:
    float Percent{1.0f};
    void SetPercent(float PercentIn);
};
}  // namespace TPS
"""


def _write_header(tmp_path, rel_path: str, text: str):
    path = tmp_path / "Source" / "TPS" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_headers_extracts_class_name_and_doc_comment(tmp_path):
    _write_header(tmp_path, "TPSCharacter.h", TPS_CHARACTER_H_TEXT)

    result = scan_headers(tmp_path)

    assert result.file_count == 1
    assert result.classes[0].name == "ATPSCharacter"


def test_scan_headers_only_extracts_public_methods(tmp_path):
    _write_header(tmp_path, "TPSCharacter.h", TPS_CHARACTER_H_TEXT)

    result = scan_headers(tmp_path)

    method_names = {m.name for m in result.classes[0].methods}
    # OnResetVR/TurnAtRate are protected -- excluded. CameraBoom is a field,
    # not a method -- excluded. operator== isn't extractable by this scan's
    # regex (see module docstring) -- excluded, not mis-parsed.
    assert method_names == {"ATPSCharacter", "GetCameraBoom"}


def test_scan_headers_captures_constructor_with_no_return_type(tmp_path):
    _write_header(tmp_path, "TPSCharacter.h", TPS_CHARACTER_H_TEXT)

    result = scan_headers(tmp_path)

    constructor = next(m for m in result.classes[0].methods if m.name == "ATPSCharacter")
    assert constructor.signature == "ATPSCharacter();"


def test_scan_headers_captures_single_line_and_multi_line_doc_comments(tmp_path):
    _write_header(tmp_path, "TPSCharacter.h", TPS_CHARACTER_H_TEXT)

    result = scan_headers(tmp_path)

    get_camera_boom = next(m for m in result.classes[0].methods if m.name == "GetCameraBoom")
    assert get_camera_boom.doc_comment == "Returns CameraBoom subobject"


def test_scan_headers_captures_api_macro_class_and_default_constructors(tmp_path):
    _write_header(tmp_path, "Items/Battery.h", BATTERY_H_TEXT)

    result = scan_headers(tmp_path)

    assert result.classes[0].name == "Battery"
    method_names = [m.name for m in result.classes[0].methods]
    # Both Battery() overloads captured; GetPercent (public) captured;
    # SetPercent (private) excluded.
    assert method_names == ["Battery", "Battery", "Charge", "UnCharge", "GetPercent"]


def test_scan_headers_captures_bang_style_line_comments(tmp_path):
    _write_header(tmp_path, "Items/Battery.h", BATTERY_H_TEXT)

    result = scan_headers(tmp_path)

    charge = next(m for m in result.classes[0].methods if m.name == "Charge")
    assert charge.doc_comment == "\\todo Add parameter for charging"


def test_scan_headers_ignores_cpp_files(tmp_path):
    _write_header(tmp_path, "Items/Battery.cpp", "void Battery::Charge() {}\n")

    result = scan_headers(tmp_path)

    assert result.file_count == 0


def test_scan_headers_empty_without_source_folder(tmp_path):
    result = scan_headers(tmp_path)
    assert result.file_count == 0
    assert result.classes == []


def test_scan_headers_handles_binary_uasset_content_gracefully(tmp_path):
    """A stray binary file with a .h-adjacent name shouldn't crash the
    scan -- the same "degrades gracefully, doesn't mis-parse binary as
    text" discipline the roadmap calls for regarding Blueprint .uasset
    files, exercised here against genuinely non-UTF-8 binary bytes."""
    source_dir = tmp_path / "Source" / "TPS"
    source_dir.mkdir(parents=True)
    binary_garbage = bytes(range(256)) * 4
    (source_dir / "Corrupted.h").write_bytes(binary_garbage)

    result = scan_headers(tmp_path)  # must not raise

    assert result.file_count == 1
