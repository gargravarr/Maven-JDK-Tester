#!/usr/bin/env python
# -*- coding: utf-8 -*-


import argparse
import logging
import json
import os
import os.path
import re
import shutil
import subprocess
import tempfile
import urllib2
import uuid
import xml.etree.ElementTree as ET

import lxml.etree

# Globals
DRY_RUN = False
WORK_DIR = os.getcwd()
MAVEN_REPOSITORY = 'http://search.maven.org'

NAMESPACE = 'http://maven.apache.org/POM/4.0.0'
NAMESPACES = { 'mvn' : NAMESPACE }
NS_PREFIX = '{' + NAMESPACE + '}'


def process_arguments():
    parser = argparse.ArgumentParser(description='Maven version tester')
    parser.add_argument('-dir', '--target-dir', metavar='URI', help='target directory', default=WORK_DIR)
    parser.add_argument('-jdk', '--target-jdk', metavar='JDK', nargs='?', help='target JDK version')
    parser.add_argument('-mvn', '--target-mvn', metavar='MVN', nargs='?', help='target Maven version')
    parser.add_argument('-art', '--artifact', metavar='ART', nargs='*', 
                        help='Maven artifact to set version, in the form groupId:artifactId:version')
    parser.add_argument('-q', '--quiet', action='store_true', help='be silent, only log warnings and errors')
    parser.add_argument('--dry-run', action='store_true', help='only do a dry run and output what would be executed')

    return parser.parse_args()


def configure_logging(quiet=None):
    """Configures logging environment.

    Defaults to DEBUG.
    """
    if quiet:
        level = logging.WARNING
    else:
        level = logging.DEBUG
    logging.basicConfig(level=level, format='%(levelname)-6s %(message)s')


def get_project_paths(path=os.getcwd()):
    """Returns a list of paths with Maven projects.

    For the given path, searches recursively for valid Maven projects and returns a list with their locations.
    """
    pom_paths = []

    # Search for pom.xml files
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


def verify_version_mismatches(jdk_version=None, mvn_version=None):
    """Checks mismatches between environment and specified versions.

    Verifies if the Java and Maven versions in the current environment match the specified arguments. If there is any
    version mismatch, returns an error message describing the issue. If everything matches, nothing is returned.
    """
    matchers = { re.compile('Java version: (\S*)') : jdk_version,
                 re.compile('Apache Maven (\S*)') : mvn_version }

    pipe = subprocess.Popen([ 'mvn', '-version' ], stdout=subprocess.PIPE)

    for line in pipe.stdout:
        for matcher in matchers.keys():
            # This will only apply matchers to versions that are set
            if matchers[ matcher ]:
                # I know I'm chomping the hell out of it, but I just can't resist!
                # Yes, caught by the Dark Side (Ugh! Perl :P)
                error_message = 'Version mismatch. System has {}; given version was {}'.format(line.rstrip('\n'), matchers[ matcher ])

                version_length = len(matchers[matcher])

                # Versions must be at least 3 characters wide - e.g 1.7, 2.2
                if version_length < 3:
                    return error_message

                match = matcher.match(line)
                if match:
                    # Tune version_length to the least common denominator
                    if len(match.group(1)) < version_length:
                        version_length = len(match.group(1))

                    # Now for the actual match!
                    if matchers[matcher][0:version_length] != match.group(1)[0:version_length]:
                        return error_message


def check_artifact(group_id, artifact_id, version, maven_repository=MAVEN_REPOSITORY):
    """Returns True if the specified artifact exists.

    Queries the central repository for the specified artifact. Returns True if exists, false otherwise. Other
    repository can be specified, to search for local artifacts.
    """

    # Query string
    query = '/solrsearch/select?q=g:"' + group_id + '"+AND+a:"' + artifact_id + '"+AND+v:"' + version + '"'

    # Get JSON info from repository
    f = urllib2.urlopen(maven_repository + query)
    result = json.loads(f.read())
    if result['response']['numFound'] != 1:
        return False

    return True


def check_dependencies(project_path, artifact_list):
    """Checks which artifacts in the specified list are present in the project dependency tree.

    Verifies if any artifact in the specified list is present in the project's dependency tree. Returns a list with the
    ones that are present. If no one is, returns None.

    Each artifact in the list must be represented by a dictionary with the keys 'artifactId', 'groupId' and 'version'
    set.
    """
    command = ['mvn', 'dependency:tree']
    artifacts_by_string = {}
    dependencies_found = []

    # Build a matcher for each artifact
    for artifact in artifact_list:
        match_string = artifact['groupId'] + ":" + artifact['artifactId'] + ":jar:"
        artifacts_by_string[match_string] = artifact

    # Save current directory
    savedir = os.getcwd()

    os.chdir(project_path)
    pipe = subprocess.Popen(command, stdout=subprocess.PIPE)

    # Scan each dependency, line by line
    for artifact_string in artifacts_by_string.keys():
        for line in pipe.stdout:
            if artifact_string in line:
                # Add to found dependencies
                dependencies_found.append(artifacts_by_string[artifact_string])
                break

    # Go back to where we were
    os.chdir(savedir)

    if len(dependencies_found) == 0:
        return None
    return dependencies_found

def update_dependencies_version(pom_tree, dependency_list):
    """Updates the specified dependencies' versions in the specified project POM.

    Changes the project's POM, so that the specified dependencies are set to the specified versions. To accomplish this,
    versions are configured in the <dependencyManagement> section. To avoid overrides, versions declared in the
    <dependencies> section of the POM are removed.
    """

    # XML Tags
    dependencies_tag = """    <dependencies>
            </dependencies>"""

    dependencymgmt_tag = """
        <dependencyManagement>
        """ + dependencies_tag + """
        </dependencyManagement>
    """

    version_template = """<version>{}</version>"""

    dependency_template = """
        <dependency>
            <groupId>{}</groupId>
            <artifactId>{}</artifactId>
            """ + version_template + """
        </dependency>
    """

    # XPath Queries
    project_xpath = '//mvn:project'
    artifact_suffix = '/mvn:artifactId[text()="{}"]/../mvn:groupId[text()="{}"]/..'
    version_suffix = 'mvn:version'

    dependencymgmt_xpath = project_xpath + '/mvn:dependencyManagement'
    dependencies_xpath = dependencymgmt_xpath + '/mvn:dependencies'

    dependencies_query = project_xpath + '/mvn:dependencies/mvn:dependency' + artifact_suffix
    dependencymgmt_query = dependencies_xpath + '/mvn:dependency' + artifact_suffix

    # Remove <version> below <dependency> section.
    for dependency in dependency_list:

        # Check if there are versions declared at the <dependency> section.
        query = dependencies_query.format(dependency['artifactId'], dependency['groupId'])

        # This supposedly should find one and only one artifact. If it founds another, well let it be. We're not here to
        # fix POMs anyway :P
        artifacts_found = pom_tree.xpath(query, namespaces=NAMESPACES)

        for artifact in artifacts_found:
            # Query for version tags
            artifact_version = artifact.xpath(version_suffix, namespaces=NAMESPACES)

            # Remove version node. Versions are handled in <dependencyManagement>
            for av in artifact_version:
                artifact.remove(av)

    # Construct <dependencyManagement> in the least invasive way. Boring! ...but needed
    # Should project_node be checked as well?
    project_node = pom_tree.xpath(project_xpath, namespaces=NAMESPACES)
    dependencymgmt_node = pom_tree.xpath(dependencymgmt_xpath, namespaces=NAMESPACES)
    dependencies_node = pom_tree.xpath(dependencies_xpath, namespaces=NAMESPACES)

    if len(dependencymgmt_node) == 0:
        dependencymgmt_node = lxml.etree.fromstring(dependencymgmt_tag)
        project_node[0].append(lxml.etree.fromstring(dependencymgmt_tag))
    else:
        # We're only interested in the node, not in the resulting list
        dependencymgmt_node = dependencymgmt_node[0]

        if len(dependencies_node) == 0:
            dependencies_node = lxml.etree.fromstring(dependencies_tag)
            dependencymgmt_node.append(dependencies_node)
        else:
            # We're only interested in the node, not in the resulting list
            dependencies_node = dependencies_node[0]

    # Update artifact versions
    for dependency in dependency_list:
        # Check if there are versions declared at the <dependency> section.
        query = dependencymgmt_query.format(dependency['artifactId'], dependency['groupId'])

        # This supposedly should find one and only one artifact. If it founds another, well let it be. We're not here to
        # fix POMs anyway :P
        artifacts_found = pom_tree.xpath(query, namespaces=NAMESPACES)

        if len(artifacts_found) == 0:
            # Not found, insert brand new
            dependency_tag = dependency_template.format(
                dependency['artifactId'], 
                dependency['groupId'], 
                dependency['version'])
            dependencies_node.append(lxml.etree.fromstring(dependency_tag))
        else:
            # Found, update version
            # Query for version tag
            for artifact in artifacts_found:
                # Query for version tags
                artifact_version = artifact.xpath(version_suffix, namespaces=NAMESPACES)

                if len(artifact_version) == 0:
                    # Not found, insert it
                    version_tag = version_template.format(dependency['version'])
                    artifact.append(lxml.etree.fromstring(version_tag))
                else:
                    # Update version node. Versions are handled in <dependencyManagement>
                    for av in artifact_version:
                        av.text = dependency['version']

    return pom_tree


def mvn_clean_install(project_path):
    """Build the project in the specified project path.

    Executes a 'mvn clean install' in the specified project path. If it is not successful, returns the output generated
    by Maven.
    """

    # Will be set if errors happen
    maven_output = None

    # Execute mvn clean install on project's directory
    pipe = subprocess.Popen(['mvn', 'clean', 'install'], stdout=subprocess.PIPE, cwd=project_path)
    exit_code = pipe.returncode

    if return_code != 0:
        maven_output = pipe.stdout.read()

    return maven_output

def main():
    global DRY_RUN, WORK_DIR

    # Process arguments
    args = process_arguments()
    DRY_RUN = args.dry_run
    configure_logging(args.quiet)

    # Validate target directory
    if not os.path.isdir(args.target_dir):
        logging.error("Invalid target directory: %s", args.target_dir)
        exit()
    # Set working directory
    WORK_DIR = args.target_dir

    # Validate Versions
    error_message = verify_version_mismatches(jdk_version=args.target_jdk, mvn_version=args.target_mvn)
    if error_message:
        logging.error(error_message)
        exit()

    # Validate and construct list of artifacts
    artifact_list = []
    if args.artifact:
        for raw_artifact in args.artifact:
            items = raw_artifact.split(':')
            if len(items) != 3:
                logging.error("Artifact %s is not in the expected format - groupId:artifactId:version.", raw_artifact)
                exit()

            # Treat each item by its name
            group_id, artifact_id, version = items[0], items[1], items[2]

            logging.info("Checking artifact %s.", raw_artifact)
            if check_artifact(group_id, artifact_id, version):
                # Append validated artifact to the list
                artifact = {'groupId' : group_id, 'artifactId' : artifact_id, 'version' : version }

                logging.debug("Appending %s to artifact list.", artifact)
                artifact_list.append(artifact)
            else:
                logging.error("Artifact %s not found.", raw_artifact)
                exit()

    # From here on, we're good to go!

    # Work on a temp copy
    if not DRY_RUN:
        WORK_DIR = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
        logging.debug("Copying %s to temp dir...", args.target_dir)
        # Copy all, except 'target' directories
        shutil.copytree(args.target_dir, WORK_DIR, ignore=shutil.ignore_patterns("target"))

    logging.debug("Working on %s", WORK_DIR)

    # Build list of projects. This is not the perfect solution, because the real deal should be checking which of those
    # are Super POMs, and then preparing the build. More on that later...
    projects = get_project_paths(WORK_DIR)

    logging.info("Scanning for projects...")
    # If no projects were found, return
    if len(projects) == 0:
        logging.error("No projects found at %s", args.target_dir)
        return
    logging.info("Found %s projects.", len(projects))

    # Check which projects use given artifacts
    if artifact_list:
        logging.info("Checking dependencies...")
        dependencies_by_project = {}
        for project in projects:
            # For each project, check which are in use
            dependencies_in_use = check_dependencies(project, artifact_list)

            # If dependencies are found, update versions in pom
            if dependencies_in_use:
                logging.debug("Project %s uses %s", project, dependencies_in_use)

                project_pom = os.path.join(project, 'pom.xml')

                # Get XML tree and update it
                pom_tree = lxml.etree.parse(project_pom)
                pom_tree = update_dependencies_version(pom_tree, dependencies_in_use)
                logging.debug("Updated dependencies for %s", project)

                if not DRY_RUN:
                    logging.debug("Writing updated POM for %s", project)
                    pom_tree.write(project_pom)

                dependencies_by_project[project] = dependencies_in_use
            else:
                logging.debug("No dependency found for %s", project)

        if len(dependencies_by_project) == 0:
            logging.error("No project use the specified dependencies: %s", args.artifact)
            return

        # Update project list
        projects = dependencies_by_project.keys()

    logging.info("%s projects are eligible to build.", len(projects))

    # Build every project
    num_projects = len(projects)
    logging.info("Building projects.")

    for project in projects:
        logging.info("%s projects remaining. Building %s ...", num_projects, project)

        if not DRY_RUN:
            error_output = mvn_clean_install(project)
            if error_output:
                logging.info("%s: FAIL", project)
            else:
                logging.info("%s: SUCCESS", project)

        num_projects -= 1


if __name__ == '__main__':
    main()
    # Cleanup used resources
    if not DRY_RUN:
        logging.debug("Removing %s", WORK_DIR)
        shutil.rmtree(WORK_DIR)
    exit()
