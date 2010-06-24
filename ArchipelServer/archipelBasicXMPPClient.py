# 
# archipelBasicXMPPClient.py
# 
# Copyright (C) 2010 Antoine Mercadal <antoine.mercadal@inframonde.eu>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Contains ArchipelBasicXMPPClient, the root class of any Archipel XMPP capable entities

This provides basic XMPP features, like connecting, auth...
"""
import xmpp
import sys
import socket
from utils import *
import uuid
import os
import base64
import hashlib
import time
import threading

LOOP_OFF = 0
"""indicates loop off status"""

LOOP_ON = 1
"""indicates loop on status"""

LOOP_RESTART = 2
"""indicates loop restart status"""


ARCHIPEL_NS_IQ_PUSH = "archipel:push"
ARCHIPEL_NS_SERVICE_MESSAGE = "headline"

ARCHIPEL_MESSAGING_HELP_MESSAGE = """
You can communicate with me using text commands, just like if you were chatting with your friends. \
I try to understand you as much as I can, but you have to be nice with me.\
Note that you can use more complex sentence than describe into the following list. For example, if you see \
in the command ["how are you"], I'll understand any sentence containing "how are you". Parameters (if any) are separated with spaces.

For example, you can send command using the following form:
command param1 param2 param3

"""


class TNArchipelBasicXMPPClient(object):
    """
    this class represent a basic XMPP Client
    """
    def __init__(self, jid, password, configuration, auto_register=True, auto_reconnect=True):
        """
        The constructor of the class.
        
        @type jid: string
        @param jid: the jid of the client.
        @type password: string
        @param password: the password of the JID account.
        """
        self.registered_actions_to_perform_on_connection = []
        
        self.xmppstatus             = None
        self.xmppstatusshow         = None
        self.xmppclient             = None
        self.vcard                  = None
        self.password               = password
        self.jid                    = jid
        self.ressource              = socket.gethostname()
        self.roster                 = None
        self.roster_retreived       = False
        self.configuration          = configuration
        self.auto_register          = auto_register
        self.auto_reconnect         = auto_reconnect
        self.messages_registrar     = []
        self.isAuth                 = False;
        self.loop_status            = LOOP_OFF
        
        log.info("jid defined as %s/%s" % (str(self.jid), self.ressource))
        
        ip_conf = self.configuration.get("GLOBAL", "machine_ip")
        if ip_conf == "auto":
            self.ipaddr = socket.gethostbyname(socket.gethostname())
        else:
            self.ipaddr = ip_conf
        
        for method in self.__class__.__dict__:
            if not method.find("__module_init__") == -1:
                m = getattr(self, method)
                m()
    
    
    
    ######################################################################################################
    ### Server connection
    ###################################################################################################### 
    
    def _connect_xmpp(self):
        """
        Initialize the connection to the the XMPP server
        
        exit on any error.
        """
        self.xmppclient = xmpp.Client(self.jid.getDomain(), debug=[]) #['dispatcher', 'nodebuilder']
        
        if self.xmppclient.connect() == "":
            log.error("unable to connect to XMPP server")
            if self.auto_reconnect:
                self.loop_status = LOOP_RESTART
                return False
            else:
                sys.exit(-1)
        
        self.loop_status = LOOP_ON
        log.info("sucessfully connected")
        return True
    
    
    def _auth_xmpp(self):
        """
        Authentify the client to the XMPP server
        """
        log.info("trying to authentify the client")
        if self.xmppclient.auth(self.jid.getNode(), self.password, self.ressource) == None:
            self.isAuth = False;
            if (self.auto_register):
                log.info("starting registration, according to propertie auto_register")
                self._inband_registration()
                return
            log.error("bad authentication. exiting")
            sys.exit(0)
        
        log.info("sucessfully authenticated")
        
        self.register_handler()
        self.xmppclient.sendInitPresence()
        self.roster = self.xmppclient.getRoster()
        self.get_vcard()
        self.isAuth = True;
        self.perform_all_registered_auth_actions()
        self.loop_status = LOOP_ON
        
    
    
    def connect(self):
        """
        Connect and auth to XMPP Server
        """
        if self.xmppclient and self.xmppclient.isConnected():
            return;
        
        if self._connect_xmpp():
            self._auth_xmpp()
        
        # self.loop()
    
    
    def disconnect(self):
        """Close the connections from XMPP server"""
        if self.xmppclient and self.xmppclient.isConnected():
            self.loop_status = LOOP_OFF
            self.isAuth = False;
            self.xmppclient.disconnect()
    
    
    
    ######################################################################################################
    ### Server registration
    ###################################################################################################### 
    
    def _inband_registration(self):
        """
        Do a in-band registration if auth fail
        """    
        if not self.auto_register:    
            return
        
        log.info("trying to register with %s to %s" % (self.jid.getNode(), self.jid.getDomain()))
        iq = (xmpp.Iq(typ='set', to=self.jid.getDomain()))    
        payload_username = xmpp.Node(tag="username")
        payload_username.addData(self.jid.getNode())
        payload_password = xmpp.Node(tag="password")
        payload_password.addData(self.password)
        iq.setQueryNS("jabber:iq:register")
        iq.setQueryPayload([payload_username, payload_password])
        
        log.info("registration information sent. wait for response")
        resp_iq = self.xmppclient.SendAndWaitForResponse(iq)
        
        if resp_iq.getType() == "error":
            log.error("unable to register : %s" % str(iq))
            sys.exit(-1)
            
        elif resp_iq.getType() == "result":
            log.info("the registration complete")
            self.loop_status = LOOP_RESTART
    
    
    def _inband_unregistration(self):
        """
        Do a in-band unregistration
        """
        log.info("trying to unregister")
        iq = (xmpp.Iq(typ='set', to=self.jid.getDomain()))
        iq.setQueryNS("jabber:iq:register")
        
        remove_node = xmpp.Node(tag="remove")
        
        iq.setQueryPayload([remove_node])
        log.info("unregistration information sent. waiting for response")
        resp_iq = self.xmppclient.send(iq)
        self.loop_status = LOOP_OFF
    
    
    
    ######################################################################################################
    ### Basic handlers
    ###################################################################################################### 
    
    def register_handler(self):
        """
        this method have to be overloaded in order to register handler for 
        XMPP events
        """
        self.xmppclient.RegisterHandler('presence', self.__process_presence_unsubscribe, typ="unsubscribe")
        self.xmppclient.RegisterHandler('presence', self.__process_presence_subscribe, typ="subscribe")
        self.xmppclient.RegisterHandler('message', self.__process_message, typ="chat")
        
        log.info("handlers registred")
        
        for method in self.__class__.__dict__:
            if not method.find("__module_register_stanza__") == -1:
                m = getattr(self, method)
                m()
    
    
    
    def __process_presence_subscribe(self, conn, presence):
        """
        Invoked when new jabber presence subscription is received.
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type presence: xmpp.Protocol.Iq
        @param presence: the received IQ
        """        
        log.info("Subscription Presence received from {0} with type {1}".format(presence.getFrom(), presence.getType()))
        self.add_jid(presence.getFrom())
        raise xmpp.NodeProcessed
    
    
    def __process_presence_unsubscribe(self, conn, presence):
        """
        Invoked when new jabber presence unsubscribtion is received.
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type presence: xmpp.Protocol.Iq
        @param presence: the received IQ
        """
        log.info("Unubscription Presence received from {0} with type {1}".format(presence.getFrom(), presence.getType()))
        #conn.send(xmpp.Presence(to=presence.getFrom(), typ="unsubscribed"))
        self.remove_jid(presence.getFrom())
        raise xmpp.NodeProcessed
    
    
    ######################################################################################################
    ### Public method
    ######################################################################################################
        
    def register_actions_to_perform_on_auth(self, method_name, args=[], oneshot=False):
        """
        Allows object to register actions (method of this class) to perform
        when the XMPP Client will be online.
        
        @type method_name: string
        @param method_name: the name of the method to launch
        @type args: Array
        @param args: an array containing the arguments to pass to the method
        """
        if self.isAuth:
            if not oneshot:
                self.registered_actions_to_perform_on_connection.append({"name":method_name, "args": args, "oneshot": oneshot})
            if hasattr(self, method_name):
                m = getattr(self, method_name)
                if args:
                    m(args)
                else:
                    m()
        else:
            self.registered_actions_to_perform_on_connection.append({"name":method_name, "args": args, "oneshot": oneshot})
    
    
    def perform_all_registered_auth_actions(self):
        """
        Parse the all the registered actions for connection, and execute them
        """
        if not self.isAuth:
            return
        
        for action in self.registered_actions_to_perform_on_connection:
            print "performing action %s" % str(action)
            if hasattr(self, action["name"]):
                m = getattr(self, action["name"])
                if action["args"] != None:
                    m(action["args"])
                else:
                    m()
            if action["oneshot"]:
                log.info("performed action %s is oneshot. removing" % str(action))
                self.registered_actions_to_perform_on_connection.remove(action)
    
    
    def change_presence(self, presence_show=None, presence_status=None):
        self.xmppstatus     = presence_status
        self.xmppstatusshow = presence_show
        
        log.info("status change: %s show:%s" % (self.xmppstatus, self.xmppstatusshow))
        
        pres = xmpp.Presence(status=self.xmppstatus, show=self.xmppstatusshow)
        #self.mass_sender.stanzas.append(pres)
        self.xmppclient.send(pres) 
    
    
    
    def __process_message(self, conn, msg):
        """
        Handler for incoming message.

        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type msg: xmpp.Protocol.Message
        @param msg: the received message 
        """
        log.info("chat message received from %s to %s: %s" % (msg.getFrom(), str(self.jid), msg.getBody()))

        reply_stanza = self.__filter_message(msg)
        if reply_stanza:
            conn.send(self.__build_reply(reply_stanza, msg))
    
    
    
    ######################################################################################################
    ### XMPP Utilities
    ###################################################################################################### 
    
    def change_status(self, presence_status):
        self.xmppstatus = presence_status
        pres = xmpp.Presence(status=self.xmppstatus, show=self.xmppstatusshow)
        #self.mass_sender.stanzas.append(pres)
        self.xmppclient.send(pres)
    
    
    def push_change(self, namespace, change, excludedgroups=None):
        """push a change using archipel push system"""
        ns = ARCHIPEL_NS_IQ_PUSH + ":" + namespace
        
        for item, info in self.roster.getRawRoster().iteritems():
            excluded = False;
            
            if excludedgroups:
                for excludedgroup in excludedgroups:
                    if info["groups"] and excludedgroup in info["groups"]:
                        excluded = True
                        break;
            
            if not excluded:
                for resource, res_info in info["resources"].iteritems():
                    send_to = item + "/" + resource
                    if not item == self.jid.getStripped():
                        push_message = xmpp.Message(typ="headline", to=send_to)
                        push_message.addChild(name="x", namespace=ns, attrs={"change": change})
                        log.info("pushing " + ns + " / " + change + " to item " + str(send_to))
                        self.xmppclient.send(push_message)
    
    
    
    def shout(self, subject, message, excludedgroups=None):
        """send a message to evrybody in roster"""
        for item, info in self.roster.getRawRoster().iteritems():
            excluded = False;
            
            if excludedgroups:
                for excludedgroup in excludedgroups:
                    if info["groups"] and excludedgroup in info["groups"]:
                        excluded = True
                        break;
            
            if not excluded:
                for resource, res_info in info["resources"].iteritems():
                    if not item == self.jid.getStripped():
                        send_to = item + "/" + resource
                        broadcast = xmpp.Message(to=send_to, body=message, typ="headline")
                        log.info("shouting message message to %s: %s" % (send_to, message))
                        self.xmppclient.send(broadcast)
    
    
    def add_jid(self, jid, groups=[]):
        """
        Add a jid to the VM Roster and authorizes it
        
        @type jid: string
        @param jid: this jid to add
        """
        log.info("adding JID %s to roster instance %s" % (str(jid), str(self.jid)))
        
        if not self.roster:
            self.roster = self.xmppclient.getRoster()
        
        self.roster.setItem(jid, groups=groups)
        self.roster.Authorize(jid)
        self.roster.Subscribe(jid)
        
        self.push_change("subscription", "added")
    
    
    def remove_jid(self, jid):
        """
        Remove a jid from roster and unauthorizes it
        
        @type jid: string
        @param jid: this jid to remove
        """
        log.info("removed jid %s" % jid)
        self.roster.Unsubscribe(jid)
        self.roster.Unauthorize(jid)
        self.roster.delItem(jid)
    
    
    def is_jid_subscribed(self, jid):
          """
          Check if the JID is authorized or not

          @type jid: string
          @param jid: the jid to check in policy
          @rtype : boolean
          @return: False if not subscribed or True if subscribed
          """ 
          try:
              self.roster.getSubscription(str(jid))
              log.info("stanza sent form authorized JID {0}".format(jid))
              return True
          except KeyError:
              log.info("stanza sent form unauthorized JID {0}".format(jid))
              return False
    
    
    def get_vcard(self):
        
        log.info("asking for own vCard")
        node_iq = xmpp.Iq(typ='get', frm=self.jid)
        node_iq.addChild(name="vCard", namespace="vcard-temp")
        
        resp = self.xmppclient.SendAndWaitForResponse(stanza=node_iq)
        self.vCard = resp.getTag("vCard")
        log.info("own vcard retrieved")
    
    
    def set_vcard_entity_type(self, params):
        """
        allows to define a vCard type for the entry
        
        @type params: dict
        @param params: adict containing at least entity_type keys, and options avatar_file key
        """
        log.info("vcard making started")

        node_iq = xmpp.Iq(typ='set', xmlns=None)
        
        type_node = xmpp.Node(tag="TYPE")
        type_node.setData(params["entity_type"])
        
        
        if (self.configuration.getboolean("GLOBAL", "use_avatar")):
            avatar_dir  = self.configuration.get("GLOBAL", "machine_avatar_directory")
            try:
                avatar_file = params["avatar_file"]
            except:
                avatar_file = "default.png"
        
            f = open(os.path.join(avatar_dir, avatar_file), "r")
            photo_data = base64.b64encode(f.read())
            f.close()
        
            node_photo_content_type = xmpp.Node(tag="TYPE")
            node_photo_content_type.setData("image/png")
                    
            node_photo_data = xmpp.Node(tag="BINVAL")
            node_photo_data.setData(photo_data)
        
            if self.vCard and self.vCard.getTag("PHOTO"):
                old_photo_binval = self.vCard.getTag("PHOTO").getTag("BINVAL").getCDATA()
                if old_photo_binval == photo_data:
                    log.info("vCard photo hasn't change.")
                    self.send_update_vcard(None, None, hashlib.sha224(photo_data).hexdigest())
            
            node_photo  = xmpp.Node(tag="PHOTO", payload=[node_photo_content_type, node_photo_data])
            node_iq.addChild(name="vCard", payload=[type_node, node_photo], namespace="vcard-temp")
            self.xmppclient.SendAndCallForResponse(stanza=node_iq, func=self.send_update_vcard, args={"photo_hash": hashlib.sha224(photo_data).hexdigest()})
        else:
            node_iq.addChild(name="vCard", payload=[type_node], namespace="vcard-temp")
            self.xmppclient.SendAndCallForResponse(stanza=node_iq, func=self.send_update_vcard)
        
        log.info("vcard information sent with type: {0}".format(params["entity_type"]))        
    
    
    def send_update_vcard(self, conn, presence, photo_hash=None):
        """
        this method is called by set_vcard_entity_type when the update of the
        vCard is OK. It will send the presence stanza to indicates the update of 
        the vCard
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type presence: xmpp.Protocol.Iq
        @param presence: the received IQ
        @type photo_hash: string
        @param photo_hash: the SHA-1 hash of the photo that changes (optionnal)
        """
        node_presence = xmpp.Presence(frm=self.jid, status=self.xmppstatus, show=self.xmppstatusshow)
        
        if photo_hash:
            node_photo_sha1 = xmpp.Node(tag="photo")
            node_photo_sha1.setData(photo_hash)
            node_presence.addChild(name="x", namespace='vcard-temp:x:update', payload=[node_photo_sha1])
        
        self.xmppclient.send(node_presence)
        log.info("vcard update presence sent") 
    
    
    
    ######################################################################################################
    ### XMPP Utilities
    ###################################################################################################### 
    
    def loop(self):
        """
        This is the main loop of the client
        FIXME : to be change in future (because it's piggy)
        """
        
        while not self.loop_status == LOOP_OFF:
            try:
                if self.loop_status == LOOP_ON:
                    if self.xmppclient.isConnected():
                        self.xmppclient.Process(30)
                
                elif self.loop_status == LOOP_RESTART:
                    if self.xmppclient.isConnected():
                        self.disconnect()
                    time.sleep(5.0)
                    self.connect()
                
            except Exception as ex:
                log.info("GREPME: Loop exception : %s. Loop status is now %d" % (ex, self.loop_status))
                
                if str(ex).find('User removed') > -1: # ok, there is something I haven't understood with exception...
                    log.info("GREPME : Account has been removed from server")
                    self.loop_status = LOOP_OFF
                
                elif self.auto_reconnect:
                    log.info("GREPME : Disconnected from server. Trying to reconnect in 5 five seconds")
                    self.loop_status = LOOP_RESTART
                    time.sleep(5.0)
                
                else:
                    log.error("GREPME : End of loop forced by exception : %s" % str(ex))
                    self.loop_status = LOOP_OFF
        
        
        if self.xmppclient.isConnected():
            self.disconnect()
    
    
    
    ######################################################################################################
    ### XMPP Message registrars
    ###################################################################################################### 
    
    def add_message_registrar_item(self, item):
        """
        Register a method described in item
        the item use the following form:
        
        {  "commands" :     ["command trigger 1", "command trigger 2"], 
            "parameters":   [
                                {"name": "param1", "description": "the description of the first param"}, 
                                {"name": "param2", "description": "the description of the second param"}
                            ], 
            "method":       self.a_method_to_launch
            "description":  "A general description of the command"
        }
        
        The "method" key take any method with type (string)aMethod(raw_command_message). The return string
        will be sent to the requester
        
        @type item: dictionnary
        @param item: the dictionnary describing the registrar item
        """
        log.info("module have registred a method %s for commands %s" % (str(item["method"]), str(item["commands"])))
        self.messages_registrar.append(item)
    
    
    def add_message_registrar_items(self, items):
        """
        register an array of item see @add_message_registrar_item
        
        @type item: array
        @param item: an array of messages_registrar items
        """
        for item in items:
            self.add_message_registrar_item(item)
    
    
    def __filter_message(self, msg):
        """
        this method filter archipel push messages and archipel service messages
        
        @type conn: xmpp.Dispatcher
        @param conn: ths instance of the current connection that send the message
        @type msg: xmpp.Protocol.Message
        @param msg: the received message
        """
        if not msg.getType() == ARCHIPEL_NS_SERVICE_MESSAGE and not msg.getType() == ARCHIPEL_NS_IQ_PUSH and not msg.getType() == "error" and msg.getBody():
            log.info("message received from %s (%s)" % (msg.getFrom(), msg.getType()))
            reply = msg.buildReply("not prepared")
            me = reply.getFrom()
            me.setResource(self.ressource)
            reply.setType("chat")
            #reply.setNamespace(ARCHIPEL_NS_SERVICE_MESSAGE)
            return reply
        else:
            log.info("message ignored from %s (%s)" % (msg.getFrom(), msg.getType()))
            return False
    
    
    def __build_reply(self, reply_stanza, msg):
        """
        parse the registrar and execute commands if necessary
        """
        
        body = "%s" % msg.getBody().lower()
        reply_stanza.setBody("not understood")
        
        if body.find("help") >= 0:
            reply_stanza.setBody(self.__build_help())
        else:
            loop = True;
            for registrar_item in self.messages_registrar:
                for cmd in registrar_item["commands"]:
                    if body.find(cmd) >= 0:
                        m = registrar_item["method"]
                        resp = m(body)
                        reply_stanza.setBody(resp)
                        loop = False
                        break
                if not loop:
                    break
        
        return reply_stanza;
    
    
    def __build_help(self):
        """
        build the help message according to the current registrar
        
        @return the string containing the help message
        """
        resp = ARCHIPEL_MESSAGING_HELP_MESSAGE
        for registrar_item in self.messages_registrar:
            cmds = str(registrar_item["commands"])
            desc = registrar_item["description"]
            params = registrar_item["parameters"]
            params_string = ""
            for p in params:
                params_string += "%s: %s\n" % (p["name"], p["description"])
                
            if params_string == "":
                params_string = "No parameters"
            else:
                params_string = params_string[:-1]
                
            resp += "%s: %s\n%s\n\n" % (cmds, desc, params_string)
        
        return resp
    


