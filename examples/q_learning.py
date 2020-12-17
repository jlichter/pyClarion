"""Demonstrates Q-learning in pyClarion."""


from pyClarion import (
    feature, features, buffer, flow_in, flow_bb, terminus, subsystem, agent,
    SimpleDomain, SimpleInterface, 
    Construct, Structure,
    AgentCycle, ACSCycle, Stimulus, MaxNodes, Lag, Repeater, ActionSelector,
    Assets, 
    nd, pprint
)

from pyClarion.components.qnets import SimpleQNet, ReinforcementMap

import random


#############
### Setup ###
#############

# This simulation demonstrates q-learning in pyClarion. 

# The task is very simple: There are two prompts A and B and each prompt is 
# associated with a specific response (e.g., "Hello" and "Goodbye"). The agent 
# must learn to match the correct response to each prompt.

# Although it is not required, it is recommended to have matplotlib installed 
# to fully benefit from this demo.

# Here is the task definition (each iteration is one trial):

class ABTask(object):
    """A task where the subject must match the prompt to the response."""

    def __init__(self, length=20):

        self.length = length

    def __iter__(self):

        for i in range(self.length):

            state = random.randint(0, 1)
            if state == 0:
                yield nd.NumDict({feature("A"): 1, feature("B"): 0})
            else:
                yield nd.NumDict({feature("A"): 0, feature("B"): 1})

    @staticmethod
    def reinforcements(stimulus, actions):
        """
        Compute ABTask reinforcements.

        Returns a reward of 1 if the stimulus prompt and action match, -1 if 
        there is a mismatch, and 0 if the standby action is taken.
        """

        actions = nd.keep(
            actions, 
            keys={
                feature("respond", "A"), 
                feature("respond", "B"), 
                feature("respond", "standby")
            }
        )
        
        stimulus = nd.keep(stimulus, keys={feature("A"), feature("B")})        
        correct = nd.MutableNumDict({feature("respond", "standby"): 0})
        _correct = nd.transform_keys(
            stimulus, func=lambda s: feature("respond", s.tag),
        )
        correct.update(2 * _correct - 1)

        r = nd.sum_by(
            correct * actions, keyfunc=lambda a: feature(("r", "respond"))
        )

        return r


### Knowledge Setup ###

# To set up the Q-Net we need to provide it with some initial information:
#   - What features are in its input domain?
#   - What features constitute its output interface?
#   - What features signal reinforcements?

# To specify all this we use pyClarion feature domains and feature interfaces.

domain = SimpleDomain({
    feature("A"), 
    feature("B"), 
})

interface = SimpleInterface(
    cmds={
        feature("respond", "A"),
        feature("respond", "B"),
        feature("respond", "standby")
    },
    defaults={
        feature("respond", "standby")
    }
)

# To specify reinforcement signals, we use a feature domain defined using the
# ReinforcementMap class. ReinforcementMap expects a mapping from features 
# representing reinforcement signals to the dimensions that they reinforce 
# (including the lag value). The mapping must be one-to-one.

r_map = ReinforcementMap(
    mapping={
        feature(("r", "respond")): ("respond", 0),
    }
)


### Agent Assembly ###

learner = Structure(
    name=agent("learner"),
    emitter=AgentCycle(),
    assets=Assets(
        domain=domain,
        interface=interface,
        r_map=r_map
    )
)

with learner:

    sensory = Construct(
        name=buffer("sensory"),
        emitter=Stimulus()
    )

    # For this example, we will provide reinforcements directly through the use 
    # of a stimulus buffer. In more sophisticated models, reinforcements may be 
    # generated by the Meta-Cognitive Subsystem.

    reinforcement = Construct(
        name=buffer("reinforcement"),
        emitter=Stimulus()
    )

    acs = Structure(
        name=subsystem("acs"),
        emitter=ACSCycle()
    )

    with acs:

        Construct(
            name=features("in"),
            emitter=MaxNodes(
                sources={buffer("sensory")}
            )
        )

        Construct(
            name=features("out"),
            emitter=MaxNodes(
                sources={flow_bb("q_net")}
            )
        )

        # For training purposes, we use a simple repeater to relay the actions 
        # selected on the previous step back to the qnet. 

        Construct(
            name=flow_in("ext_actions_lag1"),
            emitter=Repeater(source=terminus("ext_actions"))
        )

        # Here we construct the Q-Net and integrate it into the bottom level. 
        # Note that it is designated as a construct of type flow_bb. The 
        # particular emitter used here, SimpleQNet, will construct an MLP with 
        # two hidden layers containing 5 nodes each. Weight updates will occur 
        # at the end of each step (i.e., training is online) through gradient 
        # descent with backpropagation. 

        qnet = Construct(
            name=flow_bb("q_net"),
            emitter=SimpleQNet(
                x_source=features("in"),
                r_source=buffer("reinforcement"),
                a_source=flow_in("ext_actions_lag1"),
                domain=learner.assets.domain,
                interface=learner.assets.interface,
                r_map=learner.assets.r_map,
                layers=[5, 5],
                gamma=0.7,
                lr=0.3
            )
        )

        # On each trial, the q-net outputs its Q values to drive action 
        # selection at the designated terminus. The Q values are squashed prior 
        # being output to ensure that they lie in [0, 1]. 

        ext_actions = Construct(
            name=terminus("ext_actions"),
            emitter=ActionSelector(
                source=features("out"),
                client_interface=learner.assets.interface,
                temperature=0.05
            )
        )


##################
### Simulation ###
##################

# We are ready to run the task. We'll run it for 500 trials with an initial 
# reinforcement of 0.

task = ABTask(800)
r = nd.NumDict({feature(("r", "respond")): 0})
losses, rs, qs = [], [], []
for stimulus in task:

    sensory.emitter.input(stimulus)
    reinforcement.emitter.input(r)
    
    learner.step()     

    r = task.reinforcements(
        stimulus=stimulus,
        actions=ext_actions.output
    )
    q = qnet.output

    losses.append(qnet.emitter.loss)
    rs.append(r)
    qs.append(q)

# Now we collect some training statistics and display them.

losses = nd.exponential_moving_avg(*losses, alpha=0.3)

rs = [nd.transform_keys(d, func=lambda f: "r") for d in rs]
rs = nd.exponential_moving_avg(*rs, alpha=0.3)

qs = [nd.max_by(d, keyfunc=lambda f: "max(q)") for d in qs]
qs = [nd.log(d / (1 - d)) for d in qs] # Unsquash qs
qs = nd.exponential_moving_avg(*qs, alpha=0.3)

stats = dict()
for d in (nd.tabulate(*data) for data in (losses, rs, qs)):
    stats.update(d)

print("Initial statistics (smoothed, first 5 trials):")
print("         r:", [round(v, 2) for v in stats["r"][:5]])
print("    max(q):", [round(v, 2) for v in stats["max(q)"][:5]])
print("      loss:", [round(v, 2) for v in stats["loss"][:5]])
print()

print("Final statistics (smoothed, last 5 trials):")
print("         r:", [round(v, 2) for v in stats["r"][-5:]])
print("    max(q):", [round(v, 2) for v in stats["max(q)"][-5:]])
print("      loss:", [round(v, 2) for v in stats["loss"][-5:]])
print()

try:
    import matplotlib.pyplot as plt
except ImportError:
    msg = "Could not display graph of training stats: matplotlib not installed."
    print(msg)
else:
    fig, (ax1, ax2, ax3) = plt.subplots(3, sharex=True)
    fig.suptitle('Training Statistics (Smoothed Over Trials)')
    plt.xlabel("Trials")
    ax1.plot(stats["r"], alpha=0.8, label="r")
    ax1.hlines(y=0, xmin=0, xmax=task.length, alpha=0.4, linestyle='--')
    ax2.plot(stats["max(q)"],alpha=0.8, label="max(q)")
    ax3.plot(stats["loss"], alpha=0.8, label="loss")
    ax1.legend()
    ax2.legend()
    ax3.legend()
    plt.show()


##################
### CONCLUSION ###
##################

# This simple simulation sought to demonstrate q-learning in pyClarion. 
# SimpleQNet makes use of pyClarion's native autodiff support, which should be 
# sufficient for learning and experimentation, but may be too slow for more 
# heavy applications. 