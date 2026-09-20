"""Build orchestration; uses the existing builder without duplicating it."""
import time
from app_settings import (validate_build_output_directory, validate_windows_vulkan_path,
    BUILD_OUTPUT_DIRECTORY_KEY, CPU_TARGET_KEY, BUILD_JOBS_KEY)
from ui.settings import save_setting
from config import get_dir_suffix
from builder import (run_build, get_build_path, get_checkout_version, save_build_result,
    get_error_explanation, extract_error_lines)


def cmake_option_is_off(flags, option_name):
    if isinstance(flags, str):
        flags = [flags]
    state = None
    for flag in flags or []:
        expression = str(flag).strip()
        if not expression.upper().startswith('-D') or '=' not in expression:
            continue
        key, value = expression[2:].split('=', 1)
        if key.split(':', 1)[0].strip().upper() != option_name.upper():
            continue
        value = value.strip().upper()
        if value in {'OFF', 'FALSE', 'NO', 'N', '0'}:
            state = False
        elif value in {'ON', 'TRUE', 'YES', 'Y', '1'}:
            state = True
    return state is False


def build(source, profile, options, write):
    options = dict(options)
    output_dir, _ = validate_build_output_directory(options['build_output_dir'])
    validate_windows_vulkan_path(output_dir, profile['build_type'], get_dir_suffix(source))
    options['build_output_dir'] = output_dir
    save_setting(BUILD_OUTPUT_DIRECTORY_KEY, output_dir)
    save_setting(CPU_TARGET_KEY, options['cpu_target'])
    save_setting(BUILD_JOBS_KEY, options['jobs'])
    start = time.monotonic()
    success, output, error, binaries, path = run_build(
        source['id'], profile['build_type'], custom_flags=profile.get('cmake_flags', []),
        cuda_major=str(profile.get('cuda_major', '') or ''), callback=write, **options)
    duration = time.monotonic() - start
    path = path or get_build_path(source['id'], profile['build_type'], output_dir)
    save_build_result(source['id'], profile['build_type'], success, path, binaries,
                      duration, error, get_checkout_version(path))
    write('=' * 60)
    write('BUILD SUCCESSFUL!' if success else 'BUILD FAILED!')
    write(f'Duration: {duration:.1f} seconds')
    if success:
        for binary in binaries or []:
            write(str(binary))
    else:
        write(f'Error: {error}')
        for line in extract_error_lines(output):
            write(line)
        for key, value in get_error_explanation(error, output).items():
            write(f'{key.title()}: {value}')
    return {'success': success, 'path': path, 'error': error, 'duration': duration}
