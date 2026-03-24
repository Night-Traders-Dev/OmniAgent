"""Build the C accelerator extension module."""
from setuptools import setup, Extension

setup(
    name="omniagent-accel",
    ext_modules=[
        Extension(
            "src._accel",
            sources=["src/_accel.c"],
            extra_compile_args=["-O3", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2"],
        )
    ],
)
