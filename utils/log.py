import datetime
import time
import os
import requests
import subprocess

# TODO: add email function here
# TODO: more sophisticated log level: debug, info, warning, error, critical to set once when running codebase


class Logger:
    def __init__(self, webhook_url=None, filename=None):
        self.LOG_DIR = "data/logs"
        self.verbose = True
        self.webhook_url = webhook_url
        self.filename = filename

    def send_slack(self, message: str):
        """
        Send a slack message
        :param message: message to send
        :return: None
        """
        message_payload = {"text": message}
        try:
            response = requests.post(self.webhook_url, json=message_payload)
            if response.status_code == 200:
                print("Message was sent successfully to slack")
            else:
                print(
                    "Message was not sent to slack, status_code:", response.status_code
                )
        except Exception as e:
            print("An exception occurred while sending a slack message", e)

    def chirp_slack_message(
        self, masstoshare, url, id, mass, prob, plot=None, alert=None
    ):
        """
        format message for chirp mass posted to DECAM slack
        """
        if masstoshare == "MLP":
            # old mass prediction message
            message = f"*<{url}|{id}> has a total restframe mass of {round(mass)} M_sol ({alert})*"
        elif masstoshare == "chirp":
            # new chirp mass message
            if mass is None:
                message = f"*Could not locate chirp mass file for <{url}|{id}>*"
            else:
                if len(mass) == 1:
                    message = f"*<{url}|{id}> has chirp mass in bin {mass[0][0]}-{mass[0][1]}*"
                else:
                    mass_bins_formatted = ", ".join(
                        [
                            f"{m[0]}-{m[1]} ({round(100 * p, 1)}%)"
                            for m, p in zip(mass, prob)
                        ]
                    )
                    message = f"*<{url}|{id}> ({alert} alert) has chirp mass in bins {mass_bins_formatted}*"
        else:
            print("Invalid mass type specified")
            message = None
        if message:
            self.send_slack(message)

    def log_slack_message(self, message: str):
        if self.filename:
            message = f"{self.filename:} {message}"
        self.send_slack(message)

    def time_stamp(self):
        """
        :return: UTC time -> string
        """
        return datetime.datetime.utcnow().strftime("%Y%m%d_%H:%M:%S")

    def log(self, message, slack=True):
        # TODO: issue with multiple scripts logging to same file? - unlikely with our frequency
        if self.verbose:
            timestamp = self.time_stamp()
            print(f"{timestamp}: {message}")

        if not os.path.isdir(self.LOG_DIR):
            os.makedirs(self.LOG_DIR, exist_ok=True)

        date = timestamp.split("_")[0]
        with open(os.path.join(self.LOG_DIR, f"bbhbot_{date}.log"), "a") as logfile:
            logfile.write(f"{timestamp}: {message}\n")
            logfile.flush()

        # send log message to slack
        if slack:
            try:
                self.log_slack_message(f"{timestamp}: {message}\n")
            except Exception as e:
                print(f"Error sending log message to Slack: {e}")
                print("Message was:", f"{timestamp}: {message}\n")

    def heartbeat(self):
        """
        Print a hearbeat every minute - don't send slack message for this
        """
        while True:
            self.log("heartbeat", slack=False)
            time.sleep(60)


class PublishToGithub:
    def __init__(self, github_token, logger, testing=False):
        self.github_token = github_token
        self.logger = logger
        self.testing = testing

    def push_changes_to_repo(self, path_to_push):
        """
        Push changes in a given directory to the remote GitHub repository.
        """
        commit_message = "automated push by BBHBot"
        try:
            if not self.github_token:
                raise ValueError(
                    "GitHub token is missing. Please provide a valid token."
                )

            remote_url = f"https://{self.github_token}@github.com/knolan10/BBHBot.git"

            # Set the remote URL for the repository
            subprocess.run(
                ["git", "remote", "set-url", "origin", remote_url], check=True
            )

            # Stage changes in the events_summary directory
            subprocess.run(["git", "add", path_to_push], check=True)

            # Check for changes in the repository
            result = subprocess.run(
                ["git", "status", "--porcelain", path_to_push],
                capture_output=True,
                text=True,
            )
            if not result.stdout.strip():
                logmessage = f"No changes to commit in the {path_to_push}."
                self.logger.log(logmessage, slack=False)
                return

            # Commit changes
            subprocess.run(["git", "commit", "-m", commit_message], check=True)

            # Push changes to the remote repository
            subprocess.run(["git", "push", "origin", "main"], check=True)
            logmessage = "Changes pushed to the repository successfully."
            self.logger.log(logmessage, slack=False)

        except subprocess.CalledProcessError as e:
            logmessage = f"An error occurred while running a git command: {e}"
            self.logger.log(logmessage, slack=False)
        except ValueError as ve:
            logmessage = f"Error: {ve}"
            self.logger.log(logmessage, slack=False)
        except Exception as ex:
            logmessage = f"An unexpected error occurred: {ex}"
            self.logger.log(logmessage, slack=False)
