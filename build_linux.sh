#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
APT_MIRROR="${APT_MIRROR:-https://mirrors.tuna.tsinghua.edu.cn}"

APT_SOURCE_OPTIONS=()
APT_TMP_SOURCES=""

info() { printf '\033[36m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[build]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31m[build]\033[0m %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [ -n "${APT_TMP_SOURCES:-}" ]; then
        rm -f "$APT_TMP_SOURCES"
    fi
}
trap cleanup EXIT

is_root() { [ "$(id -u)" -eq 0 ]; }

run_root() {
    if is_root; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        die "安装系统软件包需要 root 权限，请以 root 运行或安装 sudo 后重试。"
    fi
}

detect_pkg_manager() {
    local pm
    for pm in apt-get dnf yum; do
        if command -v "$pm" >/dev/null 2>&1; then
            printf '%s\n' "$pm"
            return 0
        fi
    done
    return 1
}

python_is_ok() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

find_python() {
    local candidate
    if [ -n "$PYTHON" ]; then
        if command -v "$PYTHON" >/dev/null 2>&1 && python_is_ok "$PYTHON"; then
            printf '%s\n' "$PYTHON"
            return 0
        fi
        return 1
    fi
    for candidate in python3 python3.12 python3.11 python3.10 python3.9 python3.8; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_ok "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

os_release_field() {
    sed -n "s/^$1=//p" /etc/os-release 2>/dev/null | head -n 1 | tr -d '"'
}

is_ubuntu_like() {
    local id id_like
    id="$(os_release_field ID)"
    id_like="$(os_release_field ID_LIKE)"
    [ "$id" = "ubuntu" ] && return 0
    case "$id_like" in
        *ubuntu*) return 0 ;;
    esac
    return 1
}

is_debian_like() {
    local id id_like
    id="$(os_release_field ID)"
    id_like="$(os_release_field ID_LIKE)"
    [ "$id" = "debian" ] && return 0
    case "$id_like" in
        *debian*) return 0 ;;
    esac
    return 1
}

apt_arch() {
    if command -v dpkg >/dev/null 2>&1; then
        dpkg --print-architecture
    else
        uname -m
    fi
}

configure_apt_sources() {
    local codename ubuntu_codename arch base
    APT_SOURCE_OPTIONS=()
    APT_TMP_SOURCES=""
    ubuntu_codename="$(os_release_field UBUNTU_CODENAME)"
    codename="$(os_release_field VERSION_CODENAME)"
    arch="$(apt_arch)"

    if is_ubuntu_like; then
        codename="${ubuntu_codename:-$codename}"
        [ -n "$codename" ] || return 1
        case "$arch" in
            aarch64 | arm64) base="$APT_MIRROR/ubuntu-ports" ;;
            *) base="$APT_MIRROR/ubuntu" ;;
        esac
        APT_TMP_SOURCES="$(mktemp)"
        {
            printf 'deb %s %s main restricted universe multiverse\n' "$base" "$codename"
            printf 'deb %s %s-updates main restricted universe multiverse\n' "$base" "$codename"
            printf 'deb %s %s-backports main restricted universe multiverse\n' "$base" "$codename"
            printf 'deb %s %s-security main restricted universe multiverse\n' "$base" "$codename"
        } > "$APT_TMP_SOURCES"
        APT_SOURCE_OPTIONS=(-o "Dir::Etc::sourcelist=$APT_TMP_SOURCES" -o "Dir::Etc::sourceparts=-" -o "Acquire::Retries=3")
        return 0
    fi

    if is_debian_like; then
        [ -n "$codename" ] || return 1
        APT_TMP_SOURCES="$(mktemp)"
        {
            printf 'deb %s/debian %s main contrib non-free\n' "$APT_MIRROR" "$codename"
            printf 'deb %s/debian %s-updates main contrib non-free\n' "$APT_MIRROR" "$codename"
            printf 'deb %s/debian-security %s-security main contrib non-free\n' "$APT_MIRROR" "$codename"
        } > "$APT_TMP_SOURCES"
        APT_SOURCE_OPTIONS=(-o "Dir::Etc::sourcelist=$APT_TMP_SOURCES" -o "Dir::Etc::sourceparts=-" -o "Acquire::Retries=3")
        return 0
    fi

    return 1
}

apt_install() {
    local pkgs=("$@")
    if [ "${#APT_SOURCE_OPTIONS[@]}" -gt 0 ]; then
        info "使用 apt 国内镜像源：$APT_MIRROR"
        if run_root apt-get "${APT_SOURCE_OPTIONS[@]}" update; then
            if run_root apt-get "${APT_SOURCE_OPTIONS[@]}" install -y "${pkgs[@]}"; then
                return 0
            fi
            warn "国内镜像源安装失败，回退系统当前源重试。"
        else
            warn "国内镜像源更新失败，回退系统当前源。"
        fi
    else
        warn "未识别发行版代号，使用系统当前 apt 源；如需国内源请配置后重试。"
    fi
    run_root apt-get update
    run_root apt-get install -y "${pkgs[@]}"
}

install_python() {
    local pm="$1"
    info "未找到 Python 3.8+，开始通过系统包管理器安装。"
    case "$pm" in
        apt-get)
            apt_install python3 python3-pip python3-tk
            ;;
        dnf | yum)
            run_root "$pm" install -y python3 python3-pip python3-tkinter
            ;;
        *)
            die "未识别可用的包管理器，无法自动安装 Python。"
            ;;
    esac
}

ensure_pip() {
    local pm="$1"
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi
    info "pip 不可用，开始安装 python3-pip。"
    case "$pm" in
        apt-get)
            apt_install python3-pip
            ;;
        dnf | yum)
            run_root "$pm" install -y python3-pip
            ;;
        *)
            die "pip 不可用，且未识别可用的包管理器。"
            ;;
    esac
    "$PYTHON" -m pip --version >/dev/null 2>&1 || die "pip 安装后仍不可用，请检查包源与权限。"
}

ensure_tkinter() {
    local pm="$1" tk_version
    if "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
        tk_version="$("$PYTHON" -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || true)"
        info "tkinter 可用（Tk ${tk_version}）。"
        return 0
    fi
    info "tkinter 不可用，开始安装系统 tkinter 包。"
    case "$pm" in
        apt-get)
            apt_install python3-tk
            ;;
        dnf | yum)
            run_root "$pm" install -y python3-tkinter
            ;;
        *)
            die "tkinter 不可用，且未识别可用的包管理器。"
            ;;
    esac
    "$PYTHON" -c 'import tkinter' >/dev/null 2>&1 || die "tkinter 安装后仍不可用，请检查系统包源。"
}

main() {
    local pm selected_python python_version
    pm="$(detect_pkg_manager || true)"
    info "检测到包管理器：${pm:-无}"

    if [ "$pm" = "apt-get" ]; then
        configure_apt_sources || true
    fi

    if [ -n "$PYTHON" ] && { ! command -v "$PYTHON" >/dev/null 2>&1 || ! python_is_ok "$PYTHON"; }; then
        die "PYTHON=$PYTHON 不可用或版本低于 3.8。"
    fi

    selected_python="$(find_python || true)"
    if [ -z "$selected_python" ]; then
        [ -n "$pm" ] || die "未找到 Python 3.8+，且无法识别 apt-get/dnf/yum，无法自动安装。"
        install_python "$pm"
        selected_python="$(find_python || true)"
        [ -n "$selected_python" ] || die "Python 3.8+ 安装后仍未找到，请检查包源。"
    fi
    PYTHON="$selected_python"

    python_version="$("$PYTHON" -c 'import sys; print(".".join(str(v) for v in sys.version_info[:3]))')"
    info "使用 Python：$PYTHON（$python_version）"

    ensure_pip "$pm"
    ensure_tkinter "$pm"

    info "安装 Python 依赖：$PIP_INDEX"
    if "$PYTHON" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
        "$PYTHON" -m pip install -r requirements.txt -i "$PIP_INDEX" --break-system-packages
    else
        "$PYTHON" -m pip install -r requirements.txt -i "$PIP_INDEX"
    fi

    info "执行 PyInstaller 打包。"
    "$PYTHON" -m PyInstaller --clean --noconfirm ge_tool.spec
    info "构建完成：dist/GE单据OCR处理工具/GE单据OCR处理工具"
}

main "$@"
