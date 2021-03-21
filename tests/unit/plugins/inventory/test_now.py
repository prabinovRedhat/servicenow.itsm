# -*- coding: utf-8 -*-
# Copyright: (c) 2021, XLAB Steampunk <steampunk@xlab.si>
#
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import sys

import pytest

from ansible.errors import AnsibleParserError
from ansible.inventory.data import InventoryData
from ansible.module_utils.common.text.converters import to_text

from ansible_collections.servicenow.itsm.plugins.inventory import now

pytestmark = pytest.mark.skipif(
    sys.version_info < (2, 7), reason="requires python2.7 or higher"
)


@pytest.fixture
def inventory_plugin():
    plugin = now.InventoryModule()
    plugin.inventory = InventoryData()
    return plugin


class TestSysparmQueryFromConditions:
    def test_empty_conditions(self):
        assert now.sysparm_query_from_conditions({}) is None

    @pytest.mark.parametrize(
        "conditions,expected",
        [
            (dict(a=dict(includes=["b"])), "a=b"),
            (dict(a=dict(includes=["b", "c"])), "a=b^ORa=c"),
            (dict(a=dict(excludes=["b"])), "a!=b"),
            (dict(a=dict(excludes=["b", "c"])), "a!=b^a!=c"),
        ],
    )
    def test_conditions_single_field(self, conditions, expected):
        assert expected == now.sysparm_query_from_conditions(conditions)

    def test_conditions_multiple_fields(self):
        conditions = dict(
            a=dict(includes=["a1", "a2"]),
            b=dict(excludes=["b1", "b2"]),
        )
        sysparm_query = now.sysparm_query_from_conditions(conditions)

        # We do not care about the order, we just want to make sure
        # that there is "and" between conditions for both fields.
        assert sysparm_query in ("a=a1^ORa=a2^b!=b1^b!=b2", "b!=b1^b!=b2^a=a1^ORa=a2")


class TestInventoryModuleVerifyFile:
    @pytest.mark.parametrize(
        "name,valid",
        [("sample.now.yaml", True), ("sample.now.yml", True), ("invalid.yaml", False)],
    )
    def test_file_name(self, inventory_plugin, tmp_path, name, valid):
        config = tmp_path / name
        config.write_text(to_text("plugin: servicenow.itsm.now"))

        assert inventory_plugin.verify_file(to_text(config)) is valid


class TestInventoryModuleValidateGroupingConditions:
    def test_valid_named_groups(self, inventory_plugin):
        inventory_plugin.validate_grouping_conditions(
            dict(
                group1=dict(
                    col1=dict(includes=[1, 2, 3]),
                    col2=dict(excludes=[4, 5, 6]),
                ),
                group2=dict(
                    col3=dict(excludes=["a", "b"]),
                    col4=dict(includes=["c", "d"]),
                ),
            ),
            dict(),
        )

    def test_invalid_named_groups(self, inventory_plugin):
        with pytest.raises(AnsibleParserError, match="mutually exclusive"):
            inventory_plugin.validate_grouping_conditions(
                dict(
                    group=dict(
                        col=dict(includes=[1], excludes=[2]),
                    ),
                ),
                dict(),
            )

    def test_valid_group_by(self, inventory_plugin):
        inventory_plugin.validate_grouping_conditions(
            dict(),
            dict(
                col1=dict(includes=[1, 2, 3]),
                col2=dict(excludes=[4, 5, 6]),
            ),
        )

    def test_invalid_group_by(self, inventory_plugin):
        with pytest.raises(AnsibleParserError, match="mutually exclusive"):
            inventory_plugin.validate_grouping_conditions(
                dict(),
                dict(
                    col=dict(includes=[4, 5], excludes=["test"]),
                ),
            )


class TestInventoryModuleAddHost:
    def test_valid(self, inventory_plugin):
        host = inventory_plugin.add_host(
            dict(host_source="1.2.3.4", name_source="dummy_host", sys_id="123"),
            "table_name",
            "host_source",
            "name_source",
        )

        assert host == "dummy_host"
        hostvars = inventory_plugin.inventory.get_host("dummy_host").vars
        assert hostvars["ansible_host"] == "1.2.3.4"

    def test_valid_empty_host(self, inventory_plugin):
        host = inventory_plugin.add_host(
            dict(host_source="", name_source="dummy_host", sys_id="123"),
            "table_name",
            "host_source",
            "name_source",
        )

        assert host == "dummy_host"
        hostvars = inventory_plugin.inventory.get_host("dummy_host").vars
        assert "ansible_host" not in hostvars

    def test_valid_empty_name(self, inventory_plugin):
        host = inventory_plugin.add_host(
            dict(host_source="1.2.3.4", name_source="", sys_id="123"),
            "table_name",
            "host_source",
            "name_source",
        )

        assert host is None
        assert inventory_plugin.inventory.get_host("dummy_host") is None

    def test_invalid_host(self, inventory_plugin):
        with pytest.raises(AnsibleParserError, match="invalid_host"):
            inventory_plugin.add_host(
                dict(host_source="1.2.3.4", name_source="dummy_host", sys_id="123"),
                "table_name",
                "invalid_host",
                "name_source",
            )

    def test_invalid_name(self, inventory_plugin):
        with pytest.raises(AnsibleParserError, match="invalid_name"):
            inventory_plugin.add_host(
                dict(host_source="1.2.3.4", name_source="dummy_host", sys_id="123"),
                "table_name",
                "host_source",
                "invalid_name",
            )


class TestInventoryModuleSetHostvars:
    def test_valid(self, inventory_plugin):
        inventory_plugin.inventory.add_host("dummy_host")

        inventory_plugin.set_hostvars(
            "dummy_host",
            dict(sys_id="123", platform="demo", unused="column"),
            ("sys_id", "platform"),
        )

        hostvars = inventory_plugin.inventory.get_host("dummy_host").vars
        assert hostvars["sys_id"] == "123"
        assert hostvars["platform"] == "demo"
        assert "unused" not in hostvars

    def test_invalid_column(self, inventory_plugin):
        with pytest.raises(AnsibleParserError, match="bad_column"):
            inventory_plugin.set_hostvars(
                "dummy_host",
                dict(sys_id="123", platform="demo", unused="column"),
                ("sys_id", "platform", "bad_column"),
            )


class TestInventoryModuleQuery:
    def test_construction(self, inventory_plugin):
        result = inventory_plugin.query(
            dict(cname=dict(includes="b")), "host", "name", ("col1", "col2")
        )

        assert set(result["sysparm_fields"].split(",")) == set(
            ("col1", "col2", "host", "name", "sys_id", "cname")
        )
        assert result["sysparm_display_value"] is True
        assert result["sysparm_query"] == "cname=b"
