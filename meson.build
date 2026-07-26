project('vs-cfl', 'cpp',
    version: '1.0.1',
    default_options: [
        'cpp_std=c++23',
        'buildtype=release',
        'b_lto=true',
    ])

sources = files(
    'src/vs_cfl.cpp',
    'src/kACfL.cpp',
)

openmp_dep = dependency('openmp', required: false)

shared_library('vs_cfl', sources,
    include_directories: include_directories('include', 'src'),
    name_prefix: '',
    gnu_symbol_visibility: 'hidden',
    dependencies: openmp_dep,
    install: true)
