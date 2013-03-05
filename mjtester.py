#!/usr/bin/env python
# -*- coding: utf-8 -*-


import argparse
import logging
import os
import os.path
import shutil
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

import lxml.etree

NAMESPACE = 'http://maven.apache.org/POM/4.0.0'
NAMESPACES = { 'mvn' : NAMESPACE }
NS_PREFIX = '{' + NAMESPACE + '}'


def process_arguments():
    parser = argparse.ArgumentParser(description='Maven artifact tester')
    parser.add_argument('-dir', '--target-dir', metavar='URI', help='target directory', default=os.getcwd())
    parser.add_argument('-jdk', '--target-jdk', metavar='JDK', nargs='?', help='target JDK version')
    parser.add_argument('-q', '--quiet', action='store_true', help='be silent, only log warnings and errors')
    parser.add_argument('--dry-run', action='store_true', help='only do a dry run and output what would be executed')

    return parser.parse_args()


def configure_logging(quiet=None):
    if quiet:
        level = logging.WARNING
    else:
        level = logging.DEBUG
    logging.basicConfig(level=level, format='%(levelname)-6s %(message)s')


def get_pom_paths(path=os.getcwd()):
    pom_paths = []

    for root, dirs, files in os.walk(path):
        if 'pom.xml' in files:
            pom_paths.append(root)

    return pom_paths


def configure_compiler(pom_file, jdk_version):
    compiler_xpath = "//mvn:project/mvn:build/mvn:plugins/mvn:plugin/mvn:artifactId"
    maven_compiler_plugin = """
        <plugin>
            <groupId>org.apache.maven.plugins</groupId>
            <artifactId>maven-compiler-plugin</artifactId>
            <configuration>
                <source>""" + jdk_version + """</source>
                <target>""" + jdk_version + """</target>
            </configuration>
        </plugin>
        """

    pom_tree = lxml.etree.parse(pom_file)
    print lxml.etree.tostring(pom_tree)

def find_artifacts_by_group(group_id, project_path):
    command = ['mvn', 'dependency:tree']
    matcher = re.compile("\[INFO\]([\|\+\-\\\ ]+)([\w\.-]+):(.*?):")
    savedir = os.getcwd()
    artifact_set = set()

    os.chdir(project_path)
    pipe = subprocess.Popen(command, stdout=subprocess.PIPE)

    # Enable searching for dependencies
    artifact_offset = -1

    for line in pipe.stdout:
        match = matcher.match(line)
        if match:
            offset, match_group_id, artifact_id = match.group(1), match.group(2), match.group(3)
            logging.debug("%s: Matching result - Offset: (%s), Group Id: (%s), Artifact Id: (%s)",
                project_path, offset, match_group_id, artifact_id)
            if artifact_offset == -1 or len(offset) <= artifact_offset:
                # Re-enable dependency search
                artifact_offset = -1

                if match_group_id == group_id:
                    logging.info("%s: Found artifact - Artifact Id: (%s)", project_path, artifact_id)
                    artifact_set.add(artifact_id)
                    # Disable search for inner dependencies
                    artifact_offset = len(offset)

    # Go back to where we were
    os.chdir(savedir)

    if len(artifact_set) == 0:
        return None
    else:
        return artifact_set

def update_artifacts_version(pom_file, group_id, artifact_set, version):
    # XPath queries
    group_id_xpath = "//mvn:"
    # XML Tags
    group_id_tag = "<groupId>" + group_id + "</groupId>"
    artifact_id_tag = "<artifactId>{}</artifactId>"
    version_tag = "<version>" + version + "</version>"
    dependency_tag = """
        <dependency>
            """ + group_id_tag + """
            """ + artifact_id_tag + """
            """ + version_tag + """
        </dependency>
    """

    pom_tree = etree.parse(pom_file)

    # Work on a local copy
    local_artifact_set = artifact_set.copy()
    pass


def update_pom(pom_file, jdk=None):
    pom = ET.parse(pom_file)
    root = pom.getroot()

    if jdk:
        build = root.find(NS_PREFIX + 'build')
        if build is None:
            build = ET.SubElement(root, NS_PREFIX + 'build')

        plugins = build.find(NS_PREFIX + 'plugins')
        if plugins is None:
            plugins = ET.SubElement(build, NS_PREFIX + 'plugins')

        for plugin in plugins.findall(NS_PREFIX + 'plugin'):
            if plugin.findtext(NS_PREFIX + 'artifactId') == 'maven-compiler-plugin':
                plugins.remove(plugin)

        plugin = ET.SubElement(plugins, NS_PREFIX + 'plugin')

        group_id = ET.SubElement(plugin, NS_PREFIX + 'groupId')
        group_id.text = 'org.apache.maven.plugins'

        artifact_Id = ET.SubElement(plugin, NS_PREFIX + 'artifactId')
        artifact_Id.text = 'maven-compiler-plugin'

        configuration = ET.SubElement(plugin, NS_PREFIX + 'configuration')

        source = ET.SubElement(configuration, NS_PREFIX + 'source')
        source.text = jdk
        target = ET.SubElement(configuration, NS_PREFIX + 'target')
        target.text = jdk

    pom.write(pom_file, default_namespace=NAMESPACE)


def build_project_report(project_pom, build_result):

    success = '| style="background: #ACE1AF" | Success\n'
    fail = '| style="background: #FFC1CC" | FAIL\n'

    pom = ET.parse(project_pom)
    root = pom.getroot()

    group = '| ' + root.find(NS_PREFIX + 'groupId').text + '\n'
    name = '| ' + root.find(NS_PREFIX + 'artifactId').text + '\n'
    organization = root.find(NS_PREFIX + 'organization')
    organization_name = '| ' + organization.find(NS_PREFIX + 'name').text + '\n'
    result = success

    if build_result == False:
        result = fail

    return '|-\n' + group + name + organization_name + result + '''|
|
'''


def mvn_clean_install(path):
    savedir = os.getcwd()

    os.chdir(path)
    pipe = subprocess.Popen(['mvn', 'clean', 'install'], stdout=subprocess.PIPE)
    result = pipe.stdout.read()

    os.chdir(savedir)
    if re.search('BUILD SUCCESSF', result) != None:
        return True
    else:
        return False

# Checks for the correct versions in the build environment
def check_versions(jdk_version=None, mvn_version=None):
    matchers = { re.compile('Java version: (\S*)') : jdk_version,
                 re.compile('Apache Maven (\S*)') : mvn_version }

    pipe = subprocess.Popen([ 'mvn', '-version' ], stdout=subprocess.PIPE)

    for line in pipe.stdout:
        for matcher in matchers.keys():
            if matchers[ matcher ]:
                match = matcher.match(line)
                if match and matchers[ matcher ] not in match.group(1):
                    # I know I'm chomping the hell out of it, but I just can't resist!
                    # Yes, caught by the Dark Side (Perl :P)
                    return '{} - version mismatch: {}'.format(line.rstrip('\n'), matchers[ matcher ])

    return None

if __name__ == '__main__':

    # Process arguments
    args = process_arguments()
    DRY_RUN = args.dry_run
    configure_logging(args.quiet)

    # Validate Versions
    error_message = check_versions(args.target_jdk)
    if error_message:
        logging.error(error_message)
        exit()

    # Work on a local copy
    work_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
    shutil.copytree(args.target_dir, work_dir)

    # Build list of projects. This is not the perfect solution, because the real deal should be checking which of those
    # are Super POMs, and then preparing the build. More on that later...
    projects = get_pom_paths(work_dir)


    # Cleanup used resources
    shutil.rmtree(work_dir)
    exit()

    header = '{| class="wikitable sortable"\n' + '|-\n' + '! Group\n' + '! Name\n' + '! Organization/Team\n' \
        + '! Build Result\n' + '! Reason\n' + '! Solvable\n'

    footer = '|}\n'
    report = header

    project_types = ['maven-jar', 'maven-maven-plugin', 'maven-pom', 'maven-war']

    current_dir = os.getcwd()

    parser = argparse.ArgumentParser(description='Project compiler tool')
    parser.add_argument('-dir', '--target-dir', metavar='DIR', nargs='?', help='target directory', default=current_dir)
    parser.add_argument('-jdk', '--target-jdk', metavar='JDK', nargs='?', help='target JDK version')
    parser.add_argument('-cxf', '--target-cxf', metavar='CXF', nargs='?', help='target Apache CXF version')
    parser.add_argument('-mvn', '--target-mvn', metavar='MVN', nargs='?', help='target Maven version')
    parser.add_argument('-out', '--out-file', metavar='OUT', nargs='?', help='report output file')

    args = parser.parse_args()

    if args.quiet:
        level = logging.WARNING
    else:
        level = logging.DEBUG

    logging.basicConfig(level=level, format='%(levelname)-6s %(message)s')


    for project_type in project_types:
        subprocess.call([
            'python',
            'checkout.py',
            '--flatten',
            '-f',
            'type=' + project_type,
            args.target_dir,
        ])

    os.chdir(args.target_dir)
    projects = os.listdir(args.target_dir)

    # For debugging only
    # projects = projects[:5]
    numprojects = len(projects)

    for project in projects:
        print '{} projects remaining...'.format(numprojects)
        print 'Building ' + project + '...'
#        logging.info('sdfsdf %s', 234)

        project_pom = project + '/pom.xml'
        if os.path.isdir(project) and os.path.isfile(project_pom):
            # Configure build parameters
            update_pom(project_pom, jdk=args.target_jdk)

            build_result = mvn_clean_install(project)
            if build_result:
                print project + ': BUILD SUCCESSFUL'
            else:
                print project + ': BUILD FAILURE'

            project_report = build_project_report(project_pom, build_result)
            report += project_report
        else:
            print project + ': not a Maven project.'
        numprojects = numprojects - 1

    report += footer

    os.chdir(current_dir)

    if args.out_file:
        with open(args.out_file, 'w') as f:
            f.write(report)
    else:
        print report
