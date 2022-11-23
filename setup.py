from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

# get version from __version__ variable in kanosync/__init__.py
from pythacore import __version__ as version

setup(
	name='pythacore',
	version=version,
	description='Connect ERPNext to various third-party softwares.',
	author='Kano Solutions',
	author_email='contact@kanosolutions.be',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
