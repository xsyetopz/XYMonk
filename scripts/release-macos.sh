#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_NAME=$(basename "$0")
readonly SCRIPT_NAME
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
readonly REPO_ROOT
readonly KEYCHAIN_BASENAME="xymonk-release.keychain-db"
readonly STATE_BASENAME="xymonk-release-state"
readonly SEARCH_LIST_BASENAME="xymonk-release-keychains"
readonly OWNER_BASENAME="xymonk-release-owned"
readonly NOTARY_PROFILE="xymonk-release-notary"

die() {
  printf '%s: %s\n' "$SCRIPT_NAME" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_env() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || die "required environment variable is empty: $name"
  done
}

temp_path() {
  printf '%s/%s' "$RUNNER_TEMP" "$1"
}

state_file() {
  temp_path "$STATE_BASENAME"
}

keychain_path() {
  temp_path "$KEYCHAIN_BASENAME"
}

save_state() {
  local state
  state=$(state_file)
  umask 077
  {
    printf 'KEYCHAIN_PATH=%q\n' "$(keychain_path)"
    printf 'SIGNING_IDENTITY=%q\n' "$SIGNING_IDENTITY"
    printf 'TEAM_ID=%q\n' "$TEAM_ID"
  } >"$state"
}

load_state() {
  local state
  state=$(state_file)
  [[ -r "$state" ]] || die "setup state not found: $state"
  # This file is created by this script and contains only quoted, non-secret values.
  # shellcheck disable=SC1090
  source "$state"
  [[ -n "${KEYCHAIN_PATH:-}" && -n "${SIGNING_IDENTITY:-}" && -n "${TEAM_ID:-}" ]] \
    || die "setup state is incomplete"
  [[ -f "$KEYCHAIN_PATH" ]] || die "scoped signing keychain not found: $KEYCHAIN_PATH"
}

setup() {
  require_env DEVELOPER_ID_APPLICATION_CERT_BASE64 CERTIFICATE_SECRET KEYCHAIN_SECRET \
    NOTARIZE_APPLE_ID NOTARIZE_PASSWORD RUNNER_TEMP GITHUB_ENV
  require_command security
  require_command base64
  require_command xcrun
  mkdir -p "$RUNNER_TEMP"

  local keychain cert old_list identity_output cert_count old_keychain
  local -a old_keychains=()
  keychain=$(keychain_path)
  cert=$(temp_path xymonk-release-certificate.p12)
  old_list=$(temp_path "$SEARCH_LIST_BASENAME")

  [[ ! -e "$keychain" ]] || die "refusing to replace existing scoped keychain: $keychain"
  [[ ! -e "$old_list" ]] || die "refusing to replace existing search-list snapshot: $old_list"
  mkdir "$(temp_path "$OWNER_BASENAME")" || die "release signing setup already owns this temporary directory"

  security list-keychains -d user \
    | sed -nE 's/^[[:space:]]*"(.*)"[[:space:]]*$/\1/p' >"$old_list"
  [[ -s "$old_list" ]] || die "could not save the user keychain search list"

  umask 077
  printf '%s' "$DEVELOPER_ID_APPLICATION_CERT_BASE64" | base64 --decode >"$cert" \
    || die "certificate base64 decoding failed"
  security create-keychain -p "$KEYCHAIN_SECRET" "$keychain" >/dev/null 2>&1
  security set-keychain-settings -lut 21600 "$keychain" >/dev/null 2>&1
  security unlock-keychain -p "$KEYCHAIN_SECRET" "$keychain" >/dev/null 2>&1
  security import "$cert" -k "$keychain" -P "$CERTIFICATE_SECRET" \
    -T /usr/bin/codesign -T /usr/bin/security >/dev/null 2>&1
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
    -k "$KEYCHAIN_SECRET" "$keychain" >/dev/null 2>&1
  rm -f "$cert"
  while IFS= read -r old_keychain; do
    [[ -n "$old_keychain" ]] && old_keychains+=("$old_keychain")
  done <"$old_list"
  security list-keychains -d user -s "$keychain" "${old_keychains[@]}" >/dev/null 2>&1

  identity_output=$(security find-identity -v -p codesigning "$keychain" 2>/dev/null) \
    || die "could not inspect imported signing identities"
  identities=()
  while IFS= read -r identity; do
    [[ -n "$identity" ]] && identities+=("$identity")
  done < <(printf '%s\n' "$identity_output" \
    | sed -nE 's/^.*"(Developer ID Application: .+ \(([A-Za-z0-9]{10})\))"$/\1/p')
  cert_count=${#identities[@]}
  [[ "$cert_count" -eq 1 ]] || die "expected exactly one Developer ID Application identity; found $cert_count"
  SIGNING_IDENTITY=${identities[0]}
  TEAM_ID=$(printf '%s\n' "$SIGNING_IDENTITY" | sed -nE 's/^.*\(([A-Za-z0-9]{10})\)$/\1/p')
  [[ "$TEAM_ID" =~ ^[A-Za-z0-9]{10}$ ]] || die "could not derive a 10-character Team ID"

  xcrun notarytool store-credentials "$NOTARY_PROFILE" \
    --apple-id "$NOTARIZE_APPLE_ID" --team-id "$TEAM_ID" \
    --password "$NOTARIZE_PASSWORD" --keychain "$keychain" >/dev/null 2>&1 \
    || die "could not store notary credentials in the scoped keychain"

  save_state
  {
    printf 'XYMONK_RELEASE_KEYCHAIN=%s\n' "$keychain"
    printf 'XYMONK_RELEASE_SIGNING_IDENTITY=%s\n' "$SIGNING_IDENTITY"
    printf 'XYMONK_RELEASE_TEAM_ID=%s\n' "$TEAM_ID"
  } >>"$GITHUB_ENV"
  rm -f "$cert"
}

mach_o_files() {
  find "$1" -type f -print0 \
    | while IFS= read -r -d '' file; do
        if file -b "$file" | grep -q 'Mach-O'; then printf '%s\0' "$file"; fi
      done
}

sign_tree() {
  local file bundle
  local -a files=()
  while IFS= read -r -d '' file; do files+=("$file"); done < <(mach_o_files "$1")
  ((${#files[@]} > 0)) || die "no Mach-O files found in $1"
  while IFS= read -r file; do
    codesign --force --options runtime --timestamp \
      --preserve-metadata=entitlements --keychain "$KEYCHAIN_PATH" \
      --sign "$SIGNING_IDENTITY" "$file" >/dev/null
  done < <(printf '%s\n' "${files[@]}" | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-)
  # Seal nested frameworks and extensions before their containing app. LV2
  # is a directory of libraries/TTL, not an Apple code-signable bundle.
  while IFS= read -r -d '' bundle; do
    codesign --force --options runtime --timestamp \
      --preserve-metadata=entitlements --keychain "$KEYCHAIN_PATH" \
      --sign "$SIGNING_IDENTITY" "$bundle" >/dev/null
  done < <(find "$1" -depth -type d \( -name '*.framework' -o -name '*.appex' \
    -o -name '*.app' -o -name '*.clap' -o -name '*.vst3' -o -name '*.component' \) -print0)
}

verify_tree() {
  local root="$1" file details
  if [[ "$root" != *.lv2 ]]; then
    codesign --verify --deep --strict "$root" >/dev/null 2>&1 || die "signature verification failed: $root"
  fi
  while IFS= read -r -d '' file; do
    codesign --verify --strict "$file" >/dev/null 2>&1 || die "invalid Mach-O signature: $file"
    details=$(codesign -dv --verbose=4 "$file" 2>&1) || die "unsigned Mach-O: $file"
    grep -q '^Signature=adhoc$' <<<"$details" && die "ad-hoc signature remains: $file"
    grep -q 'Authority=Developer ID Application:' <<<"$details" \
      || die "unexpected signing authority: $file"
    grep -q '^Timestamp=' <<<"$details" || die "missing secure timestamp: $file"
    grep -q 'flags=.*(runtime)' <<<"$details" || die "missing hardened runtime: $file"
    grep -Fxq "TeamIdentifier=$TEAM_ID" <<<"$details" || die "unexpected signing team: $file"
    lipo "$file" -verify_arch arm64 x86_64 >/dev/null 2>&1 \
      || die "Mach-O is not universal: $file"
  done < <(mach_o_files "$root")
}

package_release() {
  require_env RELEASE_VERSION RUNNER_TEMP
  require_command codesign; require_command file; require_command find; require_command lipo
  require_command hdiutil; require_command xcrun; require_command spctl
  load_state
  [[ "$RELEASE_VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid RELEASE_VERSION"

  local bundle_dir stage artifact dmg license_source notary_json status submission_id
  bundle_dir="$REPO_ROOT/target/universal-bundles"
  stage=$(temp_path xymonk-release-stage)
  artifact="$REPO_ROOT/target/release-artifacts"
  dmg="$artifact/DelayLama-${RELEASE_VERSION}-macos-universal.dmg"
  rm -rf "$stage"
  mkdir -p "$stage/DelayLama" "$artifact"

  for bundle in 'Delay Lama.clap' 'Delay Lama.vst3' 'Delay Lama.component' 'Delay Lama.app'; do
    [[ -d "$bundle_dir/$bundle" ]] || die "expected universal bundle missing: $bundle_dir/$bundle"
    cp -R "$bundle_dir/$bundle" "$stage/DelayLama/"
  done
  [[ -d "$bundle_dir/delay-lama.lv2" ]] || die "expected universal LV2 bundle missing: $bundle_dir/delay-lama.lv2"
  cp -R "$bundle_dir/delay-lama.lv2" "$stage/DelayLama/"

  [[ -f "$REPO_ROOT/README.md" ]] || die "README.md is missing"
  mkdir -p "$stage/DelayLama/Documentation"
  cp "$REPO_ROOT/docs/install/macos.txt" "$stage/DelayLama/INSTALL.txt"
  cp "$REPO_ROOT/README.md" "$stage/DelayLama/Documentation/README.md"
  license_source=''
  for candidate in LICENSE LICENSE.txt COPYING COPYING.txt; do
    if [[ -f "$REPO_ROOT/$candidate" ]]; then license_source="$REPO_ROOT/$candidate"; break; fi
  done
  if [[ -n "$license_source" ]]; then
    cp "$license_source" "$stage/DelayLama/Documentation/$(basename "$license_source")"
  else
    # This repository keeps the original redistribution terms in README.md.
    grep -q '^## License$' "$REPO_ROOT/README.md" || die "README license terms missing"
  fi
  cp "$REPO_ROOT/CONTRIBUTING.md" "$REPO_ROOT/CODE_OF_CONDUCT.md" "$stage/DelayLama/Documentation/"

  while IFS= read -r -d '' bundle; do sign_tree "$bundle"; done < <(
    find "$stage/DelayLama" -type d \( -name '*.clap' -o -name '*.vst3' -o -name '*.component' -o -name '*.app' -o -name '*.lv2' \) -print \
      | awk '{ print gsub("/", "/"), $0 }' | sort -rn | cut -d' ' -f2- | tr '\n' '\0'
  )
  while IFS= read -r -d '' bundle; do verify_tree "$bundle"; done < <(find "$stage/DelayLama" -type d \( -name '*.clap' -o -name '*.vst3' -o -name '*.component' -o -name '*.app' -o -name '*.lv2' \) -print0)

  rm -f "$dmg"
  hdiutil create -volname "Delay Lama ${RELEASE_VERSION}" -srcfolder "$stage/DelayLama" \
    -ov -format UDZO "$dmg" >/dev/null
  codesign --force --timestamp --keychain "$KEYCHAIN_PATH" --sign "$SIGNING_IDENTITY" "$dmg" >/dev/null
  codesign --verify --strict "$dmg" >/dev/null 2>&1 || die "DMG signature verification failed"

  notary_json=$(temp_path xymonk-release-notary.json)
  xcrun notarytool submit "$dmg" --keychain-profile "$NOTARY_PROFILE" --keychain "$KEYCHAIN_PATH" \
    --wait --timeout 30m --output-format json >"$notary_json" 2>/dev/null \
    || die "notarytool submission failed or timed out"
  status=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$notary_json") \
    || die "could not parse notarytool JSON"
  [[ "$status" == 'Accepted' ]] || {
    if [[ "$status" == 'Invalid' ]]; then
      submission_id=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$notary_json")
      xcrun notarytool log "$submission_id" --keychain-profile "$NOTARY_PROFILE" \
        --keychain "$KEYCHAIN_PATH" "$(temp_path xymonk-release-notary-log.json)" >/dev/null 2>&1 || true
      if [[ -f "$(temp_path xymonk-release-notary-log.json)" ]]; then
        cat "$(temp_path xymonk-release-notary-log.json)" >&2
      fi
    fi
    die "notarization was not accepted: $status"
  }
  xcrun stapler staple "$dmg" >/dev/null 2>&1 || die "DMG stapling failed"
  xcrun stapler validate "$dmg" >/dev/null 2>&1 || die "DMG staple validation failed"
  spctl --assess --type open --context context:primary-signature "$dmg" >/dev/null 2>&1 \
    || die "Gatekeeper primary-signature assessment failed"
}

cleanup() {
  require_env RUNNER_TEMP
  require_command security
  local keychain old_list result=0
  # A failure before setup claimed its temporary paths must not delete them.
  [[ -d "$(temp_path "$OWNER_BASENAME")" ]] || return 0
  keychain=$(keychain_path)
  old_list=$(temp_path "$SEARCH_LIST_BASENAME")
  if [[ -s "$old_list" ]]; then
    old_keychains=()
    while IFS= read -r old_keychain; do
      [[ -n "$old_keychain" ]] && old_keychains+=("$old_keychain")
    done <"$old_list"
    security list-keychains -d user -s "${old_keychains[@]}" >/dev/null 2>&1 \
      || { printf '%s\n' 'could not restore the original keychain search list' >&2; result=1; }
  fi
  if [[ -e "$keychain" ]]; then
    security delete-keychain "$keychain" >/dev/null 2>&1 || result=1
  fi
  rm -f "$keychain" "$(state_file)" "$old_list" "$(temp_path xymonk-release-certificate.p12)" \
    "$(temp_path xymonk-release-notary.json)" "$(temp_path xymonk-release-notary-log.json)"
  rm -rf "$(temp_path xymonk-release-stage)"
  rmdir "$(temp_path "$OWNER_BASENAME")"
  return "$result"
}

case "${1:-}" in
  setup) setup ;;
  package) package_release ;;
  cleanup) cleanup ;;
  *) die "usage: $SCRIPT_NAME {setup|package|cleanup}" ;;
esac
