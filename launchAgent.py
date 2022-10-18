from setuptools import Command
from agent import CommanderAgent, resourcePath
import argparse
import json


def parseConfig():
    """ Set agent variables from config file """
    with open("agentConfig.json", "r") as configFile:
        configJson = json.loads(configFile.read())
        if not configJson:
            raise FileNotFoundError
    return configJson["agentID"], configJson["appName"], configJson["serverAddress"]


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log",
                        default=4,
                        help="Log level")
    args = parser.parse_args()
    # Parse agent config
    agentID, appName, serverAddress = parseConfig()
    # Launch agent
    agent = CommanderAgent(agentID=agentID,
                           appName=appName,
                           serverAddress=serverAddress,
                           logLevel=args.log)
    agent.run()