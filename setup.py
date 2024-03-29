import os
import re

from codecs import open as copen  # to use a consistent encoding
from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))


def read(*parts):
    with copen(os.path.join(here, *parts), 'r') as fp:
        return fp.read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError('Unable to find version string.')


__version__ = find_version('kg_bioportal', '__version__.py')

test_deps = [
    'pytest',
    'pytest-cov',
    'coveralls',
    'validate_version_code',
    'codacy-coverage',
    'parameterized'
]

extras = {
    'test': test_deps,
}

setup(
    name='kg_bioportal',
    version=__version__,
    description='BioPortal, as a Knowledge Graph',
    long_description='BioPortal, as a Knowledge Graph',
    url='https://github.com/Knowledge-Graph-Hub/kg_bioportal',
    author='J. Harry Caufield',
    author_email='jhc@lbl.gov',
    python_requires='>=3.7',

    # choose your license
    license='BSD-3',
    include_package_data=True,
    classifiers=[
        'Development Status :: 3 - Beta',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3'
    ],
    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    tests_require=test_deps,
    # add package dependencies
    install_requires=[
        'cat-merge',
        'click==8.0.4',
        'compress_json',
        'kaleido',
        'kghub-downloader',
        'kgx',
        'networkx',
        'pandas',
        'parameterized',
        'plotly',
        'pyyaml',
        'recommonmark',
        'sphinx',
        'sphinx_rtd_theme',
        'tqdm',
        'validate_version_code',
        'wget',
    ],
    extras_require=extras,
)
