"""
title: Ask User
author: ichrist
version: 1.0
description: Allows the LLM to autonomously trigger 1-5 interactive pop-up questions to gather missing project details.
"""

from typing import List, Optional
import time


class Tools:
    def __init__(self):
        pass

    async def get_user_clarification(
        self, questions: List[str], __event_call__=None, __event_emitter__=None
    ) -> str:
        """
        Call this tool ONLY when the user's request is too vague or requires specific parameters
        (like website style, target audience, tech stack, or color palette).
        It will present each question in a separate pop-up modal.

        :param questions: A list of 1 to 5 clear, specific questions to ask the user.
        :return: A formatted string containing the user's responses for the LLM to use.
        """
        if not __event_call__:
            return "Error: This environment does not support interactive pop-ups."

        if not questions:
            return "No questions were provided for clarification."

        # Enforce the 1-5 question limit requested
        active_questions = questions[:5]
        collected_data = []

        # Initial status message
        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": f"Gathering {len(active_questions)} specific details...",
                    "done": False,
                },
            }
        )

        for i, q in enumerate(active_questions):
            # Trigger the pop-up modal
            response = await __event_call__(
                {
                    "type": "input",
                    "data": {
                        "title": f"Clarification Step {i+1} of {len(active_questions)}",
                        "message": f"To give you the best result, I need to know:\n\n**{q}**",
                        "placeholder": "Enter your details here...",
                    },
                }
            )

            # Record result (handle empty responses)
            answer = (
                response
                if response and str(response).strip()
                else "[No information provided]"
            )
            collected_data.append(f"Q: {q}\nA: {answer}")

            # Subtle delay for UX smoothness between pop-ups
            time.sleep(0.3)

        # Final status update
        await __event_emitter__(
            {
                "type": "status",
                "data": {
                    "description": "All details received! Generating your response...",
                    "done": True,
                },
            }
        )

        # Return the data to the LLM context
        return "USER CLARIFICATION RECEIVED:\n" + "\n\n".join(collected_data)
