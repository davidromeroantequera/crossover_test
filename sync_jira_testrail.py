#!/usr/bin/python3
import re
import sys
import json 
from time import sleep

from jira import JIRA
from testrail import APIClient 


def load_configuration():
    data = {}
    with open('sync.json') as json_file:
        data = json.load(json_file)
    return data


def jira_requester():
    config = load_configuration()
    return JIRA('https://dromeroa.atlassian.net',
            basic_auth=('dromero.fisica@gmail.com', config['JIRA_TOKEN']))


def issue_keys():
    requester = jira_requester()
    return [x.key for x in requester.search_issues('')]


class Issue:
    def __init__(self, key):
        data = jira_requester().issue(key)
        self.key = key
        self.url = data.self
        self.summary = data.fields.summary

        body = data.fields.description
        self._extract_role_and_goal_from(body)
        self._extract_steps_from(body)
        self._extract_preconditions(body)

    def _extract_preconditions(self, body):
        pattern = re.compile("\\|(.*?)\\|(.*?)\\|(.*)\\|")
        self.preconditions = {}
        in_section = False
        for l in body.splitlines():
            if len(l) == 0:
                continue

            if '||' in l:
                continue

            if 'Pre-conditions' in l:
                in_section = True
                continue
            
            if in_section:
                if l[0] == '*' and l[-1] == '*':
                    break

                m = pattern.search(l)
                if m is not None:
                    self.preconditions[m.group(1)] = m.group(2)


    def _extract_role_and_goal_from(self, body):
        pattern = re.compile("\\|As a(n)? (.*?), .* able to (.*)\\|")
        in_section = False
        for l in body.splitlines():
            if len(l) == 0:
                continue

            if 'Business Goal' in l:
                in_section = True
                continue

            if in_section:
                m = pattern.search(l)
                if m is not None:
                    self.role = m.group(2)
                    self.goal = m.group(3).replace(',','')
                    return

    def _extract_steps_from(self, body):
        self.steps = []
        self.expected_results = []
        pattern = re.compile("\\|[0-9]+\\|(.*?)\\|(.*)")

        in_section = False

        in_subsection = False
        subsection_text = ''

        for l in body.splitlines():
            if len(l) == 0:
                continue

            if 'Scenario' in l:
                in_section = True
                continue

            if in_section:
                m = pattern.search(l)
                if m is not None:
                    in_subsection = True
                    if len(subsection_text) > 0:
                        self.expected_results.append(subsection_text)

                    self.steps.append(m.group(1))
                    subsection_text = m.group(2).rstrip("|") + '\n'
                    continue
                if in_subsection:
                    subsection_text += l.rstrip('|').replace('*', '-') + '\n'
            
        if len(subsection_text) > 0:
            self.expected_results.append(subsection_text)


def testrail_requester():
    config = load_configuration()
    client = APIClient("https://dromeroa.testrail.io")
    client.user = "dromero.fisica@gmail.com"
    client.password = config["TESTRAIL_TOKEN"]
    return client


def create_test_section(key, summary, url):
    requester = testrail_requester()
    response = requester.send_post('add_section/1', {
        "parent_id": 1,
        "name": key + ": " + summary,
        "description": url,
    })
    return response["id"]


def add_test_case_to_section(section, issue):
    steps = []
    for i in range(len(issue.steps)):
        steps.append({
            "content": issue.steps[i],
            "expected": issue.expected_results[i],
        })

    precond = ''
    for item, information in issue.preconditions.items():
        if 'NA' not in information:
            precond += item + ":\n" + "  - " + information +"\n"

    requester = testrail_requester()
    response = requester.send_post('add_case/{}'.format(section), {
        "title": issue.role + " is able to " + issue.goal,
        "template_id": 2,
        "type_id": 11,
        "refs": issue.key,
        "custom_steps_separated": steps,
        "custom_preconds": precond,
    })


def retrieve_test_sections():
    requester = testrail_requester()
    sections = requester.send_get("get_sections/1")
    return [x["name"] for x in sections]


def extract_keys_from_sections(sections):
    output = []
    pattern = re.compile("(.*?):")
    for x in sections:
        m = pattern.search(x)
        if m is not None:
            output.append(m.group(1))
    return output


def sync_testrail_with_jira():
    registered_keys = extract_keys_from_sections(retrieve_test_sections())
    for key in issue_keys():
        if key not in registered_keys:
            issue = Issue(key)
            section_id = create_test_section(issue.key, issue.summary, issue.url)
            add_test_case_to_section(section_id, issue)
            print("Upodating test case: {}".format(key))


def main(standby=None):
    if standby is None:
        sync_testrail_with_jira()
        return

    while (True):
        sync_testrail_with_jira()
        sleep(standby)


if __name__ == "__main__":
    standby = None
    if len(sys.argv) > 1:
        standby = int(sys.argv[1])
    main(standby)
