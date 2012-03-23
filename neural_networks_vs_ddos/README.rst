About
=====

anti_ddos.py
------------
Simple neural network for nginx log processing and classification between "bad"
and "good" clients under DDoS.

Known bugs
==========
 1. Supervised machine learning is kinda wrong for that type of problem, because to *detect bots* I first need to *detect bots* and train Neural Network with that data.
 2. I do not take client's behavior into an account. It's better to consider graph of page to page transitions for each user.
 3. I don't take clients locality into an account. If one computer in network is infected with some virus then there are more chances that other computers in that network are infected.
 4. I don't take a geolocation data into an account. Of course if you are running site in Russia there is little chance of clients from Brazil.
 5. I don't know if it was right way to use neural network and classification for solving such problem. May be I was better off with some anomaly detection system.
 6. It's better when ML method is "online" (or so-called "streaming") so it can be trained on the fly.

Approach dicussion
==================
http://stats.stackexchange.com/questions/23488/applying-machine-learning-for-ddos-filtering

Usage
=====
See ``./anti_ddos.py -h``
