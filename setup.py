from setuptools import setup

# read the contents of your README file
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='cbpi4-MashOutStep',
    version='1.0.0',
    description='CraftBeerPi 4 MashOut Step Plugin',
    author='Sammy',
    author_email='your.email@example.com',
    url='https://github.com/zzorrro/cbpi4-MashOutStep',
    include_package_data=True,
    license='MIT',
    package_data={
        '': ['*.txt', '*.rst', '*.yaml'],
        'cbpi4-MashOutStep': ['*', '*.txt', '*.rst', '*.yaml']
    },
    packages=['cbpi4-MashOutStep'],
    long_description=long_description,
    long_description_content_type='text/markdown'
)