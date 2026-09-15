project('vs-cfl', 'cpp',
    version: '1.0.2',
    default_options: [
        'cpp_std=c++20',
        'buildtype=release',
        'b_lto=true',
    ])

sources = files(
    'src/vs_cfl.cpp',
    'src/kACfL.cpp',
)

openmp_dep = dependency('openmp', required: false)
vapoursynth_dep = dependency('vapoursynth', required: false).partial_dependency(includes: true, compile_args: true)
shared_library('vs_cfl', sources,
    include_directories: include_directories('include', 'src'),
    name_prefix: '',
    gnu_symbol_visibility: 'hidden',
    dependencies: [openmp_dep, vapoursynth_dep],
    build_rpath: host_machine.system() == 'linux' ? '$ORIGIN' : '',
    install: true)
