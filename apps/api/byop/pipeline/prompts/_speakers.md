## The speakers

{% for s in speakers %}
- **{{ s.name }}**{% if loop.first and speakers|length > 1 %} (the lead host){% endif %}: {{ s.persona or "an engaged, friendly presenter" }}
{% endfor %}
{% if speakers|length == 1 %}

There is only one speaker, so write a monologue: {{ speakers[0].name }} talks to the listener directly.
{% elif speakers|length == 2 %}

Two speakers share the episode and talk to each other: they react, ask questions and add to what the other says.
{% else %}

{{ speakers|length }} speakers share the episode like a panel: the lead host guides the conversation, and every
speaker should contribute in several places, reacting to each other rather than taking turns reciting.
{% endif %}
