from dataclasses import dataclass

import httpx
from more_itertools import first

API_BASE = "https://owm.webling.ch/api/1"


@dataclass
class WeblingGroup:
    group_id: int
    title: str
    members: list[int]
    parent_group_id: int | None = None


class WeblingAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def __enter__(self):
        self.client = httpx.Client()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def fetch_membergroups(self) -> dict[int, WeblingGroup]:
        response = self.client.get(
            f"{API_BASE}/membergroup", headers={"apikey": self.api_key}, params={"format": "full"}
        )
        response.raise_for_status()

        return {
            group["id"]: WeblingGroup(
                group_id=group["id"],
                title=group["properties"]["title"],
                members=group.get("children", {}).get("member", []),
                parent_group_id=first(group.get("parents", []), None),
            )
            for group in response.json()
        }

    def fetch_members(self, parent_group: int) -> dict[int, dict]:
        response = self.client.get(
            f"{API_BASE}/member",
            headers={"apikey": self.api_key},
            params={"format": "full", "filter": f"$parents.$id={parent_group}"},
        )
        response.raise_for_status()

        return {member["id"]: member for member in response.json()}

    def update_member_contribution(self, member_id: int, contribution: int):
        response = self.client.put(
            f"{API_BASE}/member/{member_id}",
            headers={"apikey": self.api_key},
            json={"properties": {"Mitgliederbeitrag": contribution}},
        )
        response.raise_for_status()

    def create_member_group(
        self, member_ids: list[int], title: str, parent_group_id: int | None = None
    ) -> int:
        exising_groups = self.fetch_membergroups()
        if parent_group_id and parent_group_id not in exising_groups:
            raise ValueError(f"Parent group {parent_group_id} does not exist")
        title_to_id = {
            exising_group.title: exising_group.group_id
            for exising_group in exising_groups.values()
        }
        if existing_id := title_to_id.get(title):
            raise ValueError(f"Group with title {title} already exists (ID: {existing_id})")
        response = self.client.post(
            f"{API_BASE}/membergroup",
            headers={"apikey": self.api_key},
            json={
                "type": "membergroup",
                "readonly": False,
                "properties": {"title": title},
                "children": {"member": member_ids},
                **({"parents": [parent_group_id]} if parent_group_id else {}),
            },
        )
        response.raise_for_status()
        return response.json()
