# Prompt Injections and AI Agents

AI agents are increasingly used in modern software systems. Unlike a standard chatbot, an agent can perform actions, use external tools, and interact with internal company resources.

For example, an agent connected to an email system may be able to read and send messages. Another agent may review source code and interact with a code repository. Depending on its permissions, an agent can access sensitive data or perform actions that affect other systems.

A useful way to understand an AI agent is to think of it as a language model operating inside a loop. The user provides a task, and the model decides whether to answer or use an available tool. After a tool returns a result, the model uses that result to decide its next step. The loop continues until the agent can answer, reaches a configured limit, or encounters an error.

From a red-team perspective, this additional autonomy creates a larger attack surface. The security assessment should therefore focus not only on the model itself, but also on its tools, permissions, decision-making process, and access to external or internal systems.

## Single-Agent Architecture

A single agent typically has five components:

1. **Model:** Interprets the task and chooses the next step.
2. **Instructions:** Define the agent's role, goals, and boundaries.
3. **Tools:** Let the agent read data or perform actions in other systems.
4. **Context:** Holds the conversation and relevant tool results for the current task.
5. **Controller:** Runs the loop, calls tools, enforces limits, and returns the final answer.

### ReAct: reasoning and acting

**ReAct** is one way to run this loop. At each step, the agent considers its current task and the information it has, chooses an action, and observes the result. It repeats this cycle until it can produce a final answer:

```text
User task
   │
   ▼
Reason: What information or action is needed next?
   │
   ▼
Act: Call an allowed tool, or answer the user
   │
   ▼
Observe: Add the tool result to the task context
   │
   └──────────► Reason again, if the task is not complete
```

For example, an email assistant asked to summarize a message might call `search_email`, inspect the returned message, then answer the user. If the message refers to an attachment, the agent may call `read_attachment` before answering. The tool results inform the agent's next decision; they are **data**, not new instructions from the user or the system.

ReAct describes the agent's decision pattern, not a requirement to expose its private reasoning. An implementation can record tool calls, results, and brief decision summaries without displaying internal reasoning text.

### Prompt-injection risk in a ReAct loop

A tool response can contain attacker-controlled text, such as an email body, web page, or repository file. If the agent treats that text as an instruction, an attacker may redirect a later tool call or contaminate the final answer. Repeated tool use gives the injected text more opportunities to influence subsequent decisions.

When assessing a ReAct agent, trace each cycle: the user task, the tool selected, the result returned, and the next action. Check whether instructions embedded in tool results are followed, whether tool permissions are enforced outside the model, and whether sensitive or consequential actions require the appropriate authorization.

## Attack Vectors

AI applications can be attacked through several input channels. Each channel provides a different way to influence the model or the agent.

| **Input Vector** | **Description** | **Example Attack** |
| --- | --- | --- |
| Direct input | Messages sent directly by the user | Direct prompt injection |
| Uploaded content | Documents, emails, web pages, or other external data | Indirect prompt injection |
| Tool responses | Data returned by tools or external services | Tool response poisoning |
| Memory retrieval | Information loaded from previous conversations or stored memory | Memory poisoning |

Attackers may also abuse the application's output channels.

| **Output Channel** | **Description** | **Potential Abuse** |
| --- | --- | --- |
| Model response | Text returned by the model to the user | Data exfiltration |
| Tool invocation | Actions such as reading files, accessing emails, or making API calls | Unauthorized actions |
| Memory writes | Information stored for later retrieval | Persistent manipulation or backdoors |

The highest-impact attacks often connect an input vector with an output channel.

For example, an attacker may place malicious instructions inside a document that is later processed by an AI agent. If the agent follows those instructions, it could access sensitive information and expose it through its response or another available channel.

Another example is poisoning a shared knowledge source. Malicious content stored there may later influence the agent when other users interact with it. This could cause the agent to provide incorrect information, redirect users to an unsafe website, or perform an unintended action.

For this reason, red team testing should not focus only on whether a prompt injection is accepted. The important question is what the attacker can achieve after influencing the system.

### Purple Team Methodology

When red team testing is performed together with a blue team, the goal should be more than finding vulnerabilities. Both teams should use the engagement to understand attack paths, improve detection, and strengthen defensive controls.

A practical workflow can be divided into five stages.

1. **Map the system**
    
    Start by understanding the AI application and its environment. Identify the agent's purpose, available tools, connected data sources, memory mechanisms, and permissions.
    
    Test the boundaries of the system as well. For example, ask about information that should not be available to the agent and observe how it responds. However, a refusal alone should not be treated as proof that specific hidden information exists. The result should be verified through additional testing or system evidence.
    
2. **Test the basic attack**
    
    Begin with the simplest version of the attack. Avoid obfuscation or advanced bypass techniques at this stage.
    
    The objective is to confirm whether the attack path is possible and to understand how the system processes, records, and blocks the request.
    
3. **Review detection**
    
    Examine the available telemetry and security logs. Platforms such as Langfuse, SIEM systems, application logs, or custom monitoring tools may provide useful information.
    
    Determine which control detected the attack and what part of the request caused the alert. This helps both teams understand how effective the current detection logic is.
    
4. **Test bypass resistance**
    
    Modify the attack and check whether the defensive controls continue to detect it.
    
    Depending on the system, this may include testing different representations of the same malicious instruction, content embedded in external data, unusual formatting, or other transformations.
    
    The purpose is not only to bypass one rule. It is to identify whether the defense depends too heavily on a specific pattern, keyword, or representation instead of detecting the underlying malicious behavior.
    
5. **Verify the result**
    
    Repeat the test and review the telemetry again.
    
    Confirm whether the attack was blocked, detected, or successfully executed. If a modified attack is no longer detected, document the exact conditions that caused the detection gap so the blue team can improve the control.
    
    After defensive changes are introduced, run the same attack again to verify that the new protection works.
    

### Red and Blue Teams Should Improve Together

A successful red team engagement should improve both offensive testing and defensive monitoring.

The red team learns how the system behaves under adversarial conditions and identifies realistic attack paths. The blue team learns which signals are useful for detecting those attacks and where existing controls are weak.

The final goal is not simply to demonstrate that an attack works. It is to turn each successful attack into a test case that can be detected, blocked, and used to prevent similar attacks in the future.