"""Simple test to ensure that you can retreive posts"""

import os

from atproto import Client
from dotenv import load_dotenv

from pylabel import post_from_url

load_dotenv(override=True)
USERNAME = os.getenv("USERNAME")
PW = os.getenv("PW")


def main():
    """Main function"""
    client = Client()
    client.login(USERNAME, PW)
    result = post_from_url(
        client, "https://bsky.app/profile/bgrueskin.bsky.social/post/3m5vtyrngi22e"
    )
    print("Successfully loaded post:", result)


main()
