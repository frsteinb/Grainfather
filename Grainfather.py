#!/usr/bin/env python3
"""
grainfather - Manage Grainfather community brew recipes

Copyright (C) 2018 Frank Steinberg <frank@familie-steinberg.org>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
"""



import os
import re
import sys
import json
import math
import errno
import getopt
import pickle
import fnmatch
import logging
import logging.handlers
import sqlite3
import base64
import requests
import tempfile
import time
import datetime
import dateutil
import dateutil.tz
import subprocess
import http.client
import pyinotify
import asyncio
from enum import Enum
import lxml.etree
import xmltodict



DEFAULT_SOURCE		= "Frank's Grainfather Community Tool"



class Util(object):

    """Some utility function."""



    def localToUtc(t):

        u = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", 
                          time.gmtime(time.mktime(time.strptime(t, "%Y-%m-%dT%H:%M:%S"))))
        return u



    def utcToLocal(t):

        utc = datetime.datetime.strptime(t[:19], '%Y-%m-%dT%H:%M:%S')
        utc = utc.replace(tzinfo=dateutil.tz.tzutc())
        local = utc.astimezone(dateutil.tz.tzlocal())
        s = local.isoformat(sep=" ")

        return s



    def yieldToPpg(y):
        return float(y) * 0.46177



    def fToC(f):

        return (f - 32) * 5 / 9



    def platoToGravity(plato):

        # formula learned from https://www.brewersfriend.com/plato-to-sg-conversion-chart/
        return 1.0 + ( plato / ( 258.6 - ( ( plato / 258.2 ) * 227.1 ) ) )



    def ebcToLovibond(ebc):

        # from GF js: function lovi2ebc(value, dec) { return ((value * 1.3546 - 0.76) * 1.97).toFixed(dec || 0); }
        # so, in reverse:
        return ((ebc / 1.97) + 0.76) / 1.3546



    def lToGal(value):

        return value * 0.264172



    def kgToLb(value):

        return value * 2.20462



    def gToOz(value):

        return value * 0.035274



class BeerSmith3(object):

    """Representation of a BeerSmith3 database."""

    dir = None
    pattern = None
    logger = None



    def __init__(self, dir, pattern=None):

        """Initialized access to the BeerSmith3 database given by the
        filesystem directory parameter."""

        self.logger = logging.getLogger('beersmith')
        self.dir = dir
        self.pattern = pattern



    def collectBeerSmithRecipes(self, table):

        """Retrieve a list of all recipes that match the given
        name pattern in all folders."""

        l = []

        if table.__class__.__name__ != "list":
            table = [ table ]

        for entry in table:
            if entry["data"] != None:
                if (self.pattern in entry["name"]) and (entry["data"] != None):
                    recipes = entry["data"]["recipe"]
                    if recipes.__class__.__name__ != "list":
                        recipes = [ recipes ]
                    for recipe in recipes:
                        l.append(recipe)
                if "table" in entry["data"]:
                    l.extend(self.collectBeerSmithRecipes(entry["data"]["table"]))

        return l



    def dictToRecipe(self, bs):

        """Converts a BeerSmith3 recipe dict into a Recipe object."""

        data = {}
        brew_data = {}

        data["name"] = bs["f_r_name"]

        data["og"] = float("%.3f" % float(bs["f_r_desired_og"]))
        data["ibu"] = round(float(bs["f_r_desired_ibu"]))
        data["srm"] = float("%.1f" % float(bs["f_r_desired_color"]))

        data["is_active"] = True # what is this?
        data["is_public"] = True # could we allow adjustment in BeerSmith3 somehow?
        data["notes"] = bs["f_r_notes"]
        data["description"] = bs["f_r_description"]
        data["efficiency"] = float(bs["f_r_equipment"]["f_e_efficiency"]) / 100 # percent -> fraction
        data["created_at"] = bs["agedata"]["_mod_"] + "T00:00:00.000000Z"
        data["updated_at"] = bs["_mod_"] + "T00:00:00.000000Z"
        data["batch_size"] = float("%.2f" % (float(bs["f_r_equipment"]["f_e_batch_vol"]) * 0.0295735)) # fl oz -> l
        data["boil_size"] = float("%.2f" % (float(bs["f_r_equipment"]["f_e_boil_vol"]) * 0.0295735)) # TBD: at start or end of boil?
        data["boil_time"] = round(float(bs["f_r_equipment"]["f_e_boil_time"]))
        data["losses"] = float("%.02f" % (float(bs["f_r_equipment"]["f_e_trub_loss"]) * 0.0295735))
        data["unit_type_id"] = UnitType.METRIC.value; # TBD: we could derive the unit type from BeerSmith options
        if bs["f_r_style"]["f_s_guide"] == "BJCP 2015":
            data["bjcp_style_id"] = "%s%s" % (bs["f_r_style"]["f_s_number"], chr(64+int(bs["f_r_style"]["f_s_letter"])))

        # ingredients
        if ("ingredients" in bs) and ("data" in bs["ingredients"]):
            # fermentables
            data["fermentables"] = []
            grain_weight = 0.0
            if ("grain" in bs["ingredients"]["data"]):
                grains = bs["ingredients"]["data"]["grain"]
                if grains.__class__.__name__ != "list":
                    grains = [ grains ]
                for grain in grains:
                    if int(grain["f_g_use"]) == 0: # mash
                        usageType = FermentableUsageType.MASH.value
                    elif int(grain["f_g_use"]) == 1: # steep
                        usageType = FermentableUsageType.STEEP.value
                    elif int(grain["f_g_use"]) == 2: # boil
                        usageType = FermentableUsageType.EXTRACT.value
                    elif int(grain["f_g_use"]) >= 3: # whirlpool, or later
                        usageType = FermentableUsageType.LATEADDITION.value
                    else:
                        usageType = FermentableUsageType.MASH.value # default
                    data["fermentables"].append({
                            "name": grain["f_g_name"],
                            "ppg": float("%.1f" % (Util.yieldToPpg(float(grain["f_g_yield"])))),
                            "lovibond": float("%.02f" % (float(grain["f_g_color"]))), # lovibond
                            "fermentable_usage_type_id": usageType,
                            "fermentable_id": None,
                            "amount": float("%.03f" % (float(grain["f_g_amount"]) * 0.0283495))  # oz -> kg
                            })
                    grain_weight += (float(grain["f_g_amount"]) * 0.0283495) # in kg

            # hops
            data["hops"] = []
            if ("hops" in bs["ingredients"]["data"]):
                hops = bs["ingredients"]["data"]["hops"]
                if hops.__class__.__name__ != "list":
                    hops = [ hops ]
                for hop in hops:
                    if int(hop["f_h_form"]) == 0: # pellet
                        typeid = HopType.PELLET.value
                    elif int(hop["f_h_form"]) == 1: # plug
                        typeid = HopType.PLUG.value
                    elif int(hop["f_h_form"]) == 2: # leaf
                        typeid = HopType.LEAF.value
                    elif int(hop["f_h_form"]) >= 3: # extract, other form of extract
                        typeid = HopType.EXTRACT.value
                    else:
                        typeid = HopType.PELLET.value # default
                    time = round(float(hop["f_h_boil_time"]))
                    if int(hop["f_h_use"]) == 0: # boil
                        usageType = HopUsageType.BOIL.value
                    elif int(hop["f_h_use"]) == 1: # dry hop
                        usageType = HopUsageType.DRYHOP.value
                        time = round(float(hop["f_h_dry_hop_time"]))
                    elif int(hop["f_h_use"]) == 2: # mash
                        usageType = HopUsageType.MASH.value
                    elif int(hop["f_h_use"]) == 3: # first wort
                        usageType = HopUsageType.FIRSTWORT.value
                    elif int(hop["f_h_use"]) == 4: # steep / whirlpool
                        usageType = HopUsageType.HOPSTAND.value
                    else:
                        usageType = HopUsageType.BOIL.value # default
                    data["hops"].append({
                            "name": hop["f_h_name"],
                            "aa": float("%.01f" % (float(hop["f_h_alpha"]))),
                            "hop_type_id": typeid,
                            "hop_usage_type_id": usageType,
                            "time": time,
                            "amount": float("%.1f" % (float(hop["f_h_amount"]) * 28.3495)) # oz -> g
                            })

            # yeasts
            data["yeasts"] = []
            if ("yeast" in bs["ingredients"]["data"]):
                yeasts = bs["ingredients"]["data"]["yeast"]
                if yeasts.__class__.__name__ != "list":
                    yeasts = [ yeasts ]
                for yeast in yeasts:
                    name = yeast["f_y_name"]
                    if yeast["f_y_product_id"] and len(yeast["f_y_product_id"]) > 0:
                        name = name + " " + yeast["f_y_product_id"]
                    if yeast["f_y_lab"] and len(yeast["f_y_lab"]) > 0:
                        name = yeast["f_y_lab"] + " " + name
                    data["yeasts"].append({
                            "name": name,
                            "unit": "packets",
                            "attenuation": float("%.02f" % (float(yeast["f_y_max_attenuation"]) / 100)),
                            "amount": float("%.1f" % (float(yeast["f_y_amount"])))
                            })
                
            # adjuncts
            data["adjuncts"] = []
            if ("misc" in bs["ingredients"]["data"]):
                miscs = bs["ingredients"]["data"]["misc"]
                if miscs.__class__.__name__ != "list":
                    miscs = [ miscs ]
                for misc in miscs:
                    if int(misc["f_m_units"]) == 0:
                        unit = "mg"
                    elif int(misc["f_m_units"]) == 1:
                        unit = "g"
                    elif int(misc["f_m_units"]) == 2:
                        unit = "oz"
                    elif int(misc["f_m_units"]) == 3:
                        unit = "lb"
                    elif int(misc["f_m_units"]) == 4:
                        unit = "kg"
                    elif int(misc["f_m_units"]) == 5:
                        unit = "ml"
                    elif int(misc["f_m_units"]) == 6:
                        unit = "tsp"
                    elif int(misc["f_m_units"]) == 7:
                        unit = "tbsp"
                    elif int(misc["f_m_units"]) == 8:
                        unit = "cup"
                    elif int(misc["f_m_units"]) == 9:
                        unit = "pt"
                    elif int(misc["f_m_units"]) == 10:
                        unit = "qt"
                    elif int(misc["f_m_units"]) == 11:
                        unit = "l"
                    elif int(misc["f_m_units"]) == 12:
                        unit = "gal"
                    elif int(misc["f_m_units"]) == 13:
                        unit = "items"
                    else:
                        unit = "units"
                    time = float(misc["f_m_time"])
                    if int(misc["f_m_use"]) == 0: # boil
                        if time == 0:
                            usageType = AdjunctUsageType.FLAMEOUT.value
                        else:
                            usageType = AdjunctUsageType.BOIL.value
                    elif int(misc["f_m_use"]) == 1: # mash
                        usageType = AdjunctUsageType.MASH.value
                        time = round(float(hop["f_h_dry_hop_time"]))
                    elif int(misc["f_m_use"]) == 2: # primary
                        usageType = AdjunctUsageType.PRIMARY.value
                    elif int(misc["f_m_use"]) == 3: # secondary
                        usageType = AdjunctUsageType.SECONDARY.value
                    elif int(misc["f_m_use"]) == 4: # bottling
                        usageType = AdjunctUsageType.BOTTLE.value
                    elif int(misc["f_m_use"]) == 5: # sparge
                        usageType = AdjunctUsageType.SPARGE.vlue
                    else:
                        usageType = AdjunctUsageType.BOIL.value
                    data["adjuncts"].append({
                            "name": misc["f_m_name"],
                            "adjunct_usage_type_id": usageType,
                            "unit": unit,
                            "amount": float("%.2f" % (float(misc["f_m_amount"]))),
                            "time": time
                            })

        # mash
        if ("f_r_mash" in bs) and ("steps" in bs["f_r_mash"]) and ("data" in bs["f_r_mash"]["steps"]) and ("mashstep" in bs["f_r_mash"]["steps"]["data"]):
            # mash steps
            data["mash_steps"] = []
            steps = bs["f_r_mash"]["steps"]["data"]["mashstep"]
            if steps.__class__.__name__ != "list":
                steps = [ steps ]
            i = 0
            for step in steps:
                data["mash_steps"].append({
                        "order": i,
                        "name": step["f_ms_name"],
                        "temperature": round(Util.fToC(float(step["f_ms_step_temp"]))),
                        "time": round(float(step["f_ms_step_time"]))
                        })
                i += 1

        # fermentation steps
        data["fermentation_steps"] = []
        if "f_r_age" in bs:
            i = 0
            a = bs["f_r_age"]
            n = a["f_a_name"]
            if int(a["f_a_type"]) >= 0:
                data["fermentation_steps"].append({
                        "order": i,
                        "name": n + ", Primary",
                        "temperature": round(Util.fToC(float(a["f_a_prim_temp"]))),
                        "time": round(float(a["f_a_prim_days"]))
                        })
                i += 1
            if int(a["f_a_type"]) >= 1:
                data["fermentation_steps"].append({
                        "order": i,
                        "name": n + ", Secondary",
                        "temperature": round(Util.fToC(float(a["f_a_sec_temp"]))),
                        "time": round(float(a["f_a_sec_days"]))
                        })
                i += 1
            if int(a["f_a_type"]) >= 2:
                data["fermentation_steps"].append({
                        "order": i,
                        "name": n + ", Tertiary",
                        "temperature": round(Util.fToC(float(a["f_a_tert_temp"]))),
                        "time": round(float(a["f_a_tert_days"]))
                        })
                i += 1
            if float(a["f_a_age"]) > 0:
                ageSuffix = ""
                if a["f_a_age_temp"] != a["f_a_end_age_temp"]:
                    ageSuffix = " (end temp %s°C)" % (round(Util.fToC(float(a["f_a_end_age_temp"]))))
                data["fermentation_steps"].append({
                        "order": i,
                          "name": n + ", Age" + ageSuffix,
                          "temperature": round(Util.fToC(float(a["f_a_age_temp"]))),
                          "time": round(float(a["f_a_age"]))
                          })
            
        # finally create the Recipe and Brew objects from the dicts
        r = Recipe(data=data, brew_data=brew_data)

        r.recalculate(force=True)

        return r



    def getRecipes(self, namepattern="*"):

        """Retrieves an array of Recipe objects from the BeerSmith3
        database based on an optional name pattern."""

        recipes = []

        # BeerSmith XML is no real XML :-( - use HTML parser to allow HTML entities
        parser = lxml.etree.HTMLParser(recover=True)

        tree = lxml.etree.parse("%s/Recipe.bsmx" % (self.dir), parser=parser)
        b = lxml.etree.tostring(tree.getroot(), method="xml")
        doc = xmltodict.parse(b.decode("utf-8"))
        bs_recipes = self.collectBeerSmithRecipes(doc["html"]["body"]["recipe"]["data"]["table"])

        bs_recipes = list(filter(lambda r: fnmatch.fnmatch(r["f_r_name"], namepattern), bs_recipes))

        print(json.dumps(bs_recipes, sort_keys=True, indent=4))

        for bs_recipe in bs_recipes:
            recipe = self.dictToRecipe(bs_recipe)
            recipes.append(recipe)
        
        return recipes



    def getRecipe(self, namepattern):

        """Retrieves one Recipe object from the BeerSmith3 database
        based on a name pattern."""

        recipes = self.getRecipes(namepattern)

        if len(recipes) == 0:
            self.logger.warn("pattern did not result in any entry")
            return None

        if len(recipes) > 1:
            self.logger.warn("pattern did not result in a unique entry")
            return None

        return recipes[0]



class KleinerBrauhelfer(object):

    """Representation of a "Kleiner Brauhelfer" database."""

    path = None
    conn = None
    logger = None



    def __init__(self, path):

        """Opens the KBH SQlite3 database given by the filesystem path parameter."""

        self.logger = logging.getLogger('kbh')
        self.path = path

        self.reopen()



    def reopen(self):

        if self.conn:
            self.conn.close()

        fd = os.open(self.path, os.O_RDONLY)
        os.close(fd)
        self.conn = sqlite3.connect(self.path, uri=True)
        self.conn.row_factory = sqlite3.Row



    def extractFromText(self, text, tag, default=None):

        """Extracts a value from a given text addressed by a given tag.
        This is used to encode some special attributes in KBH comment fields
        that are not otherwise represented in the KBH database. E.g.
        the substring "[[BJCP-Style: 7B]]" in a recipe comment may be
        converted to an according Grainfather recipe attribute."""

        value = default
        
        for line in text.splitlines():
            if ("[[%s:" % (tag)) in line:
                pattern = r'^.*\[\[' + re.escape(tag) + r' *: *([^\]]*)\]\].*$'
                value = re.sub(pattern, r'\1', line, re.IGNORECASE)

        if default != None:
            if default.__class__.__name__ == "bool":
                if str(value).lower() in [ "1", "true", "y", "yes", "ja" ]:
                    value = True
                #if str(value).lower() in [ "0", "false", "n", "no", "nein" ]:
                else:
                    value = False
                    
        return value



    def sudToRecipe(self, sud):

        """Converts a "sud" read from the KBH database into a Recipe object.
        Subsequent readings from the database will be issued to fill the
        Recipe object with as much useful information as passible."""

        c = self.conn.cursor()

        restextrakt = 0

        c.execute("SELECT * FROM Hauptgaerverlauf WHERE SudID = ? ORDER BY Zeitstempel", (sud["ID"],))
        a = c.fetchall()
        fermentation_days_hg = None
        fermentation_temp_hg = None
        if len(a) > 0:
            # get FG (in Plato) from last entry of "Hauptgaerverlauf"
            restextrakt = float(a[-1]["SW"])
            if sud["BierWurdeAbgefuellt"]:
                # get fermentation days from first and last entry of "Hauptgaerverlauf"
                start = datetime.datetime.strptime(a[0]["Zeitstempel"][:10], '%Y-%m-%d')
                end = datetime.datetime.strptime(a[-1]["Zeitstempel"][:10], '%Y-%m-%d')
                fermentation_days_hg = (end - start).days
            fermentation_temp_hg = round(sum(i["Temp"] for i in a) / len(a))

        c.execute("SELECT * FROM Nachgaerverlauf WHERE SudID = ? ORDER BY Zeitstempel", (sud["ID"],))
        a = c.fetchall()
        fermentation_days_ng = None
        fermentation_temp_ng = None
        if len(a) > 0:
            if sud["BierWurdeAbgefuellt"]:
                # get fermentation days from first and last entry of "Nachgaerverlauf"
                start = datetime.datetime.strptime(a[0]["Zeitstempel"][:10], '%Y-%m-%d')
                end = datetime.datetime.strptime(a[-1]["Zeitstempel"][:10], '%Y-%m-%d')
                fermentation_days_ng = (end - start).days
            fermentation_temp_ng = round(sum(i["Temp"] for i in a) / len(a))

        fermentation_days_sud = None
        if sud["BierWurdeAbgefuellt"]:
            # get fermentation days from brew day and bottling/kegging day
            start = datetime.datetime.strptime(sud["Anstelldatum"], '%Y-%m-%d')
            end = datetime.datetime.strptime(sud["Abfuelldatum"], '%Y-%m-%d')
            fermentation_days_sud = (end - start).days

        data = {}
        brew_data = {}

        data["name"] = sud["Sudname"]
        if sud["erg_Alkohol"] > 0:
            data["abv"] = sud["erg_Alkohol"]
        data["batch_size"] = sud["WuerzemengeAnstellen"]
        data["boil_size"] = sud["WuerzemengeKochende"] # TBD: at start or end of boil?
        data["boil_time"] = sud["KochdauerNachBitterhopfung"]
        data["og"] = float("%.03f" % Util.platoToGravity(sud["SWAnstellen"]))
        data["fg"] = float("%.03f" % Util.platoToGravity(restextrakt))

        # formula from https://brauerei.mueggelland.de/vergaerungsgrad.html
        stammwuerze = float(sud["SWAnstellen"])
        wfg = 0.1808 * stammwuerze + 0.1892 * restextrakt;
        d = 261.1 / (261.53 - restextrakt);
        abw = (stammwuerze - wfg) / (2.0665 - 0.010665 * stammwuerze);
        kcal = round((6.9 * abw + 4 * ( wfg - 0.1 )) * 10 * 0.1 * d);
        # we reverse engineered this calories factor
        data["calories"] = round(kcal * 3.55)
        # dates seem to be overwritten by the GF server
        data["created_at"] = Util.localToUtc(sud["Erstellt"])
        data["updated_at"] = Util.localToUtc(sud["Gespeichert"])
        # pick description from first paragraph of "Kommentar"
        data["description"] = sud["Kommentar"].splitlines()[0]
        data["efficiency"] = float("%.2f" % (sud["erg_Sudhausausbeute"] / 100.0))
        data["ibu"] = sud["IBU"]
        data["bggu"] = float(data["ibu"]) / (float(data["og"]) - 1.0) / 1000
        if sud["WuerzemengeAnstellen"] > 0 and sud["WuerzemengeVorHopfenseihen"] > 0:
            data["losses"] = float("%.1f" % (sud["WuerzemengeVorHopfenseihen"] - sud["WuerzemengeAnstellen"]))
        else:
            data["losses"] = 2.0 # default losses by trub and chiller
        data["notes"] = re.sub(r'\[\[[^\]]*\]\]\n?', r'', sud["Kommentar"])
        data["srm"] = float("%.1f" % (float(sud["erg_Farbe"]) * 0.508))
        data["bjcp_style_id"] = self.extractFromText(sud["Kommentar"], "BJCP-Style")
        data["is_active"] = True # what is this?
        data["is_public"] = self.extractFromText(sud["Kommentar"], "Public", default=False)
        data["unit_type_id"] = UnitType.METRIC.value;
        
        # fermentables
        data["fermentables"] = []
        grain_weight = 0.0
        c.execute("SELECT * FROM Malzschuettung WHERE SudID = ? ORDER BY Prozent DESC", (sud["ID"],))
        malze = c.fetchall()
        for malz in malze:
            ausbeute = self.extractFromText(malz["Kommentar"], "Ausbeute", default=80)
            ppg = float("%.1f" % (Util.yieldToPpg(ausbeute)))
            data["fermentables"].append({
                    "name": malz["Name"],
                    "ppg": ppg,
                    "lovibond": float("%.3f" % Util.ebcToLovibond(float(malz["Farbe"]))),
                    "fermentable_usage_type_id": FermentableUsageType.MASH.value, # kbh supports just mash for "Malz"
                    "fermentable_id": None,
                    "amount": float("%.3f" % (malz["erg_Menge"])) })
            grain_weight += malz["erg_Menge"]
        # we assume "Weitere Zutaten" with "Ausbeute > 0" are other fermentables
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND Typ != 100 AND Ausbeute > 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            if zutat["Zeitpunkt"] == 2:
                usage = FermentableUsageType.MASH.value
            elif zutat["Zeitpunkt"] == 1:
                usage = FermentableUsageType.EXTRACT.value
            elif zutat["Zeitpunkt"] == 0:
                usage = FermentableUsageType.LATEADDITION.value
            ppg = float("%.1f" % (Util.yieldToPpg(float(zutat["Ausbeute"]))))
            data["fermentables"].append({
                    "name": zutat["Name"],
                    "ppg": ppg,
                    "lovibond": float("%.3f" % Util.ebcToLovibond(float(zutat["Farbe"]))),
                    "fermentable_usage_type_id": usage,
                    "fermentable_id": None,
                    "amount": float("%.3f" % (zutat["erg_Menge"] / 1000)) })
            grain_weight += zutat["erg_Menge"] / 1000

        # hops
        data["hops"] = []
        # first wort
        c.execute("SELECT * FROM HopfenGaben WHERE SudID = ? AND Vorderwuerze = 1 ORDER BY erg_Menge DESC", (sud["ID"],))
        diehopfen = c.fetchall()
        for hopfen in diehopfen:
            if hopfen["Pellets"] == 1:
                typeid = HopType.PELLET.value
            else:
                typeid = HopType.LEAF.value
            data["hops"].append({
                    "name": hopfen["Name"],
                    "aa": hopfen["Alpha"],
                    "hop_type_id": typeid,
                    "hop_usage_type_id": HopUsageType.FIRSTWORT.value,
                    "time": data["boil_time"],
                    "amount": float("%.3f" % (hopfen["erg_Menge"])) })
        # boil and hopstand
        c.execute("SELECT * FROM HopfenGaben WHERE SudID = ? AND Vorderwuerze = 0 ORDER BY Zeit DESC", (sud["ID"],))
        diehopfen = c.fetchall()
        for hopfen in diehopfen:
            if hopfen["Pellets"] == 1:
                typeid = HopType.PELLET.value
            else:
                typeid = HopType.LEAF.value
            if hopfen["Zeit"] == 0:
                usage = HopUsageType.HOPSTAND.value
                time = 0
            elif hopfen["Zeit"] < 0:
                usage = HopUsageType.HOPSTAND.value
                time = 0
            else:
                usage = HopUsageType.BOIL.value
                time = hopfen["Zeit"]
            data["hops"].append({
                    "name": hopfen["Name"],
                    "aa": hopfen["Alpha"],
                    "time": time,
                    "hop_type_id": typeid,
                    "hop_usage_type_id": usage,
                    "amount": float("%.3f" % (hopfen["erg_Menge"])) })
        # dry hop
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND ( Typ = 100 OR Typ = -1 ) AND Zeitpunkt = 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            c.execute("SELECT * FROM Hopfen WHERE Beschreibung = ?", (zutat["Name"],))
            hopfen = c.fetchone()
            if hopfen:
                aa = hopfen["Alpha"]
                if hopfen["Pellets"] == 1:
                    typeid = HopType.PELLET.value
                else:
                    typeid = HopType.LEAF.value
            else:
                aa = 0
                typeid = HopType.PELLET.value
            data["hops"].append({
                    "name": zutat["Name"],
                    "hop_usage_type_id": HopUsageType.DRYHOP.value,
                    "aa": aa,
                    "hop_type_id": typeid,
                    "unit": "g",
                    "amount": float("%.3f" % (zutat["erg_Menge"])) })
            if zutat["Zugabedauer"] > 0:
                t = zutat["Zugabedauer"]
                if t >= 1440:
                    t = round(t / 1440)
                data["hops"][-1]["time"] = t
            else:
                data["hops"][-1]["time"] = 0

        # yeast (kbh supports only one yeast in a recipe)
        if sud["HefeAnzahlEinheiten"] == 0:
            data["yeasts"] = []
        else:
            data["yeasts"] = [ { "name": sud["AuswahlHefe"], "amount": sud["HefeAnzahlEinheiten"], "unit": "packets" } ]
            c.execute("SELECT * FROM Hefe WHERE Beschreibung = ?", (sud["AuswahlHefe"],))
            hefe = c.fetchone()
            if hefe:
                data["yeasts"][0]["attenuation"] = int(re.sub(r'^([0-9]+).*$', r'\1', hefe["EVG"])) / 100
                if hefe["TypTrFl"] == 1:
                    data["yeasts"][0]["unit"] = "packets"
                else:
                    data["yeasts"][0]["unit"] = "vials"
                try:
                    amount = float(re.sub(r'^([0-9\.,]*).*$', r'\1', hefe["Verpackungsmenge"]).replace(",","."))
                    unit = re.sub(r'^[0-9\., ]*(.*)$', r'\1', hefe["Verpackungsmenge"])
                    if (amount > 0) and (unit in YeastUnitTypes):
                        data["yeasts"][0]["amount"] = amount * data["yeasts"][0]["amount"]
                        data["yeasts"][0]["unit"] = unit
                except:
                    self.logger.debug("could not convert Hefe Verpackungsmenge \"%s\" to amount and unit" % (hefe["Verpackungsmenge"]))
                
        # adjuncts
        data["adjuncts"] = []
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND Typ != 100 AND Typ != -1 AND Ausbeute <= 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            if zutat["Zeitpunkt"] == 2:
                usage = AdjunctUsageType.MASH.value
            elif zutat["Zeitpunkt"] == 1:
                if zutat["Zugabedauer"] == 0:
                    usage = AdjunctUsageType.FLAMEOUT.value
                else:
                    usage = AdjunctUsageType.BOIL.value
            elif zutat["Zeitpunkt"] == 0:
                usage = AdjunctUsageType.PRIMARY.value
            data["adjuncts"].append({
                    "name": zutat["Name"],
                    "adjunct_usage_type_id": usage,
                    "unit": "g",
                    "amount": float("%.3f" % (zutat["erg_Menge"])) })
            if zutat["Zugabedauer"] > 0:
                t = zutat["Zugabedauer"]
                if t >= 1440:
                    t = round(t / 1440)
                data["adjuncts"][-1]["time"] = t

        # mash steps
        data["mash_steps"] = []
        i = 0
        c.execute("SELECT * FROM Rasten WHERE SudID = ?", (sud["ID"],))
        rasten = c.fetchall()
        for rast in rasten:
            data["mash_steps"].append({
                    "order": i,
                    "name": rast["RastName"],
                    "temperature": rast["RastTemp"],
                    "time": rast["RastDauer"] })
            i += 1

        # fermentation steps
        data["fermentation_steps"] = []
        i = 0
        fermentation_string = self.extractFromText(sud["Kommentar"], "Fermentation")
        if (not fermentation_string) or (fermentation_string[0] == ","):
            if fermentation_days_sud and (fermentation_days_sud >= 1) and (fermentation_days_sud <= 30):
                days = fermentation_days_sud
            elif fermentation_days_hg and (fermentation_days_hg >= 1) and (fermentation_days_hg <= 30):
                days = fermentation_days_hg
            else:
                days = 14
            if fermentation_temp_hg:
                temp = fermentation_temp_hg
            # TBD: fetch temp from KBH Hefe alternatively
            else:
                temp = 18
            data["fermentation_steps"].append({
                    "order": i,
                    "name": "Hauptgärung",
                    "temperature": temp,
                    "time": days })
            i += 1
        if fermentation_string and ":" in fermentation_string and "@" in fermentation_string:
            steps = fermentation_string.split(",")
            for step in steps:
                if ":" in step and "@" in step:
                    name = step.split(":")[0]
                    days = step.split(":")[1].split("@")[0].replace(" ", "")
                    temp = step.split("@")[1].replace(" ", "")
                    data["fermentation_steps"].append({
                            "order": i,
                            "name": name,
                            "temperature": temp,
                            "time": days })
                    i += 1
        else:
            if fermentation_days_ng and (fermentation_days_ng >= 1) and (fermentation_days_ng <= 30):
                days = fermentation_days_ng
                if fermentation_temp_ng:
                    temp = fermentation_temp_ng
                # TBD: fetch temp from KBH Hefe alternatively
                else:
                    temp = 18
                data["fermentation_steps"].append({
                        "order": i,
                        "name": "Nachgärung",
                        "temperature": temp,
                        "time": days })
                i += 1

        # brew session
        brew_data["created_at"] = data["created_at"]
        brew_data["updated_at"] = data["updated_at"]
        brew_data["is_active"] = data["is_active"]
        brew_data["is_public"] = data["is_public"]
        brew_data["unit_type_id"] = data["unit_type_id"]
        brew_data["grain_weight"] = grain_weight
        brew_data["boil_time"] = data["boil_time"]
        brew_data["strike_water_volume"] = sud["erg_WHauptguss"]
        brew_data["sparge_water_volume"] = sud["erg_WNachguss"]
        brew_data["total_water_needed"] = brew_data["strike_water_volume"] + brew_data["sparge_water_volume"]
        brew_data["strike_water_temp"] = sud["EinmaischenTemp"]
        #brew_data["boil_volume_est"] = 
        #brew_data["ferment_volume_est"] = 

        
        if sud["BierWurdeVerbraucht"]:
            brew_data["status"] = BrewStatusType.COMPLETE
        elif sud["BierWurdeAbgefuellt"]:
            # Note: the transition from CONDITIONING to COMPLETE is
            # dynamic, it depends on the current date compared to the
            # kegging date plus conditioning weeks.
            d = datetime.datetime.strptime(sud["Abfuelldatum"][:10], '%Y-%m-%d') + datetime.timedelta(weeks = sud["Reifezeit"])
            if  datetime.datetime.now() > d:
                brew_data["status"] = BrewStatusType.COMPLETE
            else:
                brew_data["status"] = BrewStatusType.CONDITIONING
        elif sud["BierWurdeGebraut"]:
            brew_data["status"] = BrewStatusType.FERMENTATION
        else:
            brew_data["status"] = BrewStatusType.BREWDAY

        # finally create the Recipe and Brew objects from the dicts
        r = Recipe(data=data, brew_data=brew_data)

        r.recalculate()

        return r


        
    def getRecipes(self, namepattern="*"):

        """Retrieves an array of Recipe objects from the KBH database
        based on an optional name pattern."""

        namepattern = namepattern.replace("*", "%")

        c = self.conn.cursor()
        c.execute("SELECT * FROM Sud WHERE Sudname LIKE ?", (namepattern,))
        sude = c.fetchall()

        recipes = []
        for sud in sude:
            recipe = self.sudToRecipe(sud)
            recipes.append(recipe)

        return recipes



    def getRecipe(self, namepattern):

        """Retrieves one Recipe object from the KBH database based on
        a name pattern."""

        recipes = self.getRecipes(namepattern)

        if len(recipes) == 0:
            self.logger.warn("pattern did not result in any entry")
            return None

        if len(recipes) > 1:
            self.logger.warn("pattern did not result in a unique entry")
            return None

        return recipes[0]



    def getBrew(self, recipe=None, namepattern=None):

        """Retrieves a Brew objects from the KBH database based on
        either a given Recipe object or an SQL recipe name pattern
        (use e.g. % as a wildcard)."""

        if not recipe:

            recipes = self.getRecipes(namepattern)

            if len(recipes) == 0:
                self.logger.warn("pattern did not result in any entry")
                return None

            if len(recipes) > 1:
                self.logger.warn("pattern did not result in a unique entry")
                return None

            recipe = recipes[0]



class Session(object):

    """Representation of a user session on the Grainfather brew community database."""
    
    session = None
    username = None
    metadata = None
    logger = None
    readonly = False
    headers = {}
    cookies = None



    def get(self, url, relogin=True):

        response = self.session.get(url, headers=self.headers, cookies=self.cookies, allow_redirects=False)
        self.logger.info("GET %s -> %s" % (url, response.status_code))
        if (response.status_code == 302) and ("/login" in response.headers["Location"]):
            if relogin:
                # if the response seems to be the login page
                self.login()
            response = self.session.get(url, headers=self.headers, cookies=self.cookies)
            self.logger.info("GET %s -> %s" % (url, response.status_code))
        return response



    def post(self, url, data=None, json=None, files=None, force=False, relogin=True):

        if (self.readonly == False) or force:
            response = self.session.post(url, headers=self.headers, cookies=self.cookies, data=data, json=json, files=files, allow_redirects=False)
            self.logger.info("POST %s -> %s" % (url, response.status_code))
            if (response.status_code == 302) and ("/login" in response.headers["Location"]):
                if relogin:
                    # if the response seems to be the login page
                    self.login()
                response = self.session.post(url, headers=self.headers, cookies=self.cookies, data=data, json=json, files=files)
                self.logger.info("POST %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("POST %s (dryrun)" % (url))
            response = None
        return response



    def put(self, url, data=None, json=None, force=False, relogin=True):

        if (self.readonly == False) or force:
            response = self.session.put(url, headers=self.headers, cookies=self.cookies, data=data, json=json, allow_redirects=False)
            self.logger.info("PUT %s -> %s" % (url, response.status_code))
            if (response.status_code == 302) and ("/login" in response.headers["Location"]):
                if relogin:
                    # if the response seems to be the login page
                    self.login()
                response = self.session.put(url, headers=self.headers, cookies=self.cookies, data=data, json=json)
                self.logger.info("PUT %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("PUT %s (dryrun)" % (url))
            response = None
        return response



    def delete(self, url, force=False, relogin=True):

        if (self.readonly == False) or force:
            response = self.session.delete(url, headers=self.headers, cookies=self.cookies, allow_redirects=False)
            self.logger.info("DELETE %s -> %s" % (url, response.status_code))
            if (response.status_code == 302) and ("/login" in response.headers["Location"]):
                if relogin:
                    # if the response seems to be the login page
                    self.login()
                response = self.session.delete(url, headers=self.headers, cookies=self.cookies)
                self.logger.info("DELETE %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("DELETE %s (dryrun)" % (url))
            response = None
        return response



    def saveState(self, response):
        
        # save session information persistently for subsequent program calls
        state = dict(
            username = self.username,
            metadata = self.metadata,
            cookies = response.cookies.get_dict()
            )
        with open(os.path.expanduser(self.stateFile), "w") as f:
            json.dump(state, f, sort_keys=True, indent=4)
        self.logger.info("Saved session state to %s" % (self.stateFile))


    def loadState(self):

        try:
            f = open(os.path.expanduser(self.stateFile))
            state = json.load(f)
            f.close()
            self.username = state["username"]
            self.metadata = state["metadata"]
            self.headers.update({'X-CSRF-TOKEN': self.metadata["csrfToken"]})
            self.cookies = state["cookies"]
            self.logger.info("Read session state from %s" % (self.stateFile))
        except Exception as error:
            self.logger.debug("No valid session state found at %s: %s" % (self.stateFile, error))



    def removeState(self):

        os.remove(os.path.expanduser(self.stateFile))
        self.logger.info("Removed session state file %s" % (self.stateFile))



    def __init__(self, username=None, password=None, readonly=False, force=False, stateFile=None):

        self.username = username
        self.password = password
        self.readonly = readonly
        self.force = force
        self.stateFile = stateFile

        self.logger = logging.getLogger('session')

        self.session = requests.session()

        if self.stateFile:
            self.loadState()

        if not self.metadata:
            self.login()



    def login(self):
        
            # fetch the login page
            response = self.get("https://oauth.grainfather.com/customer/account/login/", relogin=False)

            # pick the form_key from the login form
            form_key = None
            for line in response.text.splitlines():
                if "form_key" in line:
                    form_key = re.sub(r'^.*value="([a-zA-Z_0-9]*).*$', r'\1', line)
            if (not form_key):
                self.logger.error("Could not fetch form_key from login page")

            # post to the login form
            payload = {'form_key': form_key, 'login[username]': self.username, 'login[password]': self.password}
            response = self.post("https://oauth.grainfather.com/customer/account/loginPost/", data=payload, relogin=False)

            # fetch start page from the recipe creator
            response = self.get("https://brew.grainfather.com", relogin=False)

            # pick session metadata from response and set the CSRF token for this session
            self.metadata = None
            for line in response.text.splitlines():
                if "window.Grainfather" in line:
                    s = re.sub(r'window.Grainfather *= *', r'', line)
                    self.metadata = json.loads(s)
            if (not self.metadata):
                self.logger.error("Could not fetch session metadata from login response")

            self.saveState(response)



    def logout(self):

        response = self.get("https://brew.grainfather.com/logout", relogin=False)

        self.removeState()



    def register(self, obj, id=None):

        """If the given object has been defined locally and is not yet registered to
        a Grainfather session, this method will register it without actually saving
        it to the Grainfather site. Saving can be done by a subsequent save() call
        on the object."""

        if id:
            obj.set("id", id)

        if obj.session == None:
            obj.session = self
        else:
            self.logger.error("%s is already registered to a session" % obj)



    def __str__(self):

        return "<Session of user %s>" % (self.username)



    def getRecipe(self, id):

        return Recipe(self, id=id)



    def getMyRecipes(self, namepattern=None, full=False, brews=False):

        recipes = []

        url = "https://brew.grainfather.com/my-recipes/data?page=1"

        while url:

            response = self.get(url)
            responsedata = json.loads(response.text)

            for data in responsedata["data"]:
                recipe = Recipe(data=data)
                self.register(recipe)
                recipes.append(recipe)
                    
            if "next_page_url" in responsedata:
                url = responsedata["next_page_url"]
            else:
                break

        if namepattern:
            recipes = list(filter(lambda r: fnmatch.fnmatch(r.get("name"), namepattern), recipes))

        if full:
            for recipe in recipes:
                recipe.reload()

        if brews:
            for recipe in recipes:
                recipe.getBrews(full=full)

        return recipes



    def getMyRecipe(self, namepattern=None, full=True, brews=False):

        recipes = self.getMyRecipes(namepattern, full=full, brews=brews)

        if len(recipes) == 0:
            self.logger.warn("pattern did not result in any entry")
            return None

        if len(recipes) > 1:
            self.logger.warn("pattern did not result in a unique entry")
            return None

        return recipes[0]



class AdjunctUsageType(Enum):

    MASH		= 10	# min
    SPARGE		= 15	# min
    BOIL		= 20	# min
    FLAMEOUT		= 25	# min
    PRIMARY		= 30	# days
    SECONDARY		= 40	# days
    BOTTLE		= 50	# min



class FermentableUsageType(Enum):

    MASH		= 10
    EXTRACT		= 20
    STEEP		= 30
    LATEADDITION	= 40	# what is this? probably after boil during fermentation or even later?



class HopType(Enum):

    LEAF		= 10
    PELLET		= 20
    PLUG		= 30
    EXTRACT             = 40    # ???


class HopUsageType(Enum):

    MASH		= 10	# min
    FIRSTWORT		= 15	# min
    BOIL		= 20	# min
    HOPSTAND		= 30	# min # obsolete?
    AROMA		= 30	# min
    DRYHOP		= 40	# days



class RecipeType(Enum):

    ALLGRAIN		= 10
    # TBD: others?



class UnitType(Enum):

    METRIC		= 10
    # TBD: others?



YeastUnitTypes = [ "packets", "vials", "g", "ml" ]



AdjunctUnitTypes = [ "each", "kg", "g", "l", "ml", "tbsp", "tsp" ]



class BrewStatusType(Enum):

    BREWDAY		= 10
    FERMENTATION	= 20
    CONDITIONING	= 30
    COMPLETE		= 40

    def getName(id):
        
        if id == BrewStatusType.BREWDAY:
            return "Brew Day"
        elif id == BrewStatusType.FERMENTATION:
            return "Fermentation"
        elif id == BrewStatusType.CONDITIONING:
            return "Conditioning"
        elif id == BrewStatusType.COMPLETE:
            return "Complete"
        else:
            return "Unknown"



class Object(object):

    session = None
    data = None



    def __init__(self, session=None, id=None, data=None):

        self.session = session
        self.data  = data

        self.tidy()
        
        if self.session:
            
            if id:

                self.reload(id=id)

            elif data:
                
                self.save()



    def tidy(self):

        return



    def reload(self, id=None):

        if not id:
            id = self.data["id"]

        response = self.session.get(self.urlload.format(api_token=self.session.metadata["user"]["api_token"], id=id))
        self.data = json.loads(response.text)



    def save(self, id=None):

        if id:
            self.data["id"] = id

        self.tidy()

        if self.isBound():
            response = self.session.put(self.urlsave.format(api_token=self.session.metadata["user"]["api_token"], id=self.data["id"]), json=self.data)
        else:
            response = self.session.post(self.urlcreate.format(api_token=self.session.metadata["user"]["api_token"]), json=self.data)

        if response:
            self.data = json.loads(response.text)



    def delete(self):

        response = self.session.delete(self.urlsave.format(api_token=self.session.metadata["user"]["api_token"], id=self.data["id"]))



    def __str__(self):

        s = "<"
        if "status" in self.data:
            s += "%s " % self.data["status"]
        else:
            if self.session:
                s += "registered "
            else:
                s += "unregistered "
        s += "%s" % (self.__class__.__name__)
        if "id" in self.data:
            s += " id %s" % self.data["id"]
        if "name" in self.data:
            s += " named \"%s\"" % self.data["name"]
        s += ">"

        return s



    def __repr__(self):

        return self.__str__()



    def set(self, attr, value):

        self.data[attr] = value



    def get(self, attr):

        if attr in self.data:
            return self.data[attr]
        else:
            return None



    def isBound(self):

        """Checks whether the object has a server-side representation."""

        if "id" in self.data:
            return True
        else:
            return False



    def isFull(self):

        """Checks whether the object contains all attributes. When
        false, some attributes may be missing, which happens for
        search results, for example."""

        if "fermentables" in self.data:
            return True
        else:
            return False



    def print(self):

        if self.isBound() and (not self.isFull()):
            self.reload()

        print(json.dumps(self.data, sort_keys=True, indent=4))



class Recipe(Object):

    urlload = "https://brew.grainfather.com/recipes/data/{id}"
    urlsave = "https://brew.grainfather.com/recipes/{id}"
    urlcreate = "https://brew.grainfather.com/recipes"

    brews = None



    def __init__(self, session=None, id=None, xmlfilename=None, data=None, brew_data=None):

        if session and xmlfilename:

            # post xml to convert to json
            self.session.logger.info("Converting XML recipe file to JSON")
            response = self.session.post("https://brew.grainfather.com/recipes/xml", files={'xml': (filename, open(filename, 'rb'), 'text/xml')})
            data = json.loads(response.text)

        super(Recipe, self).__init__(session=session, id=id, data=data)

        if brew_data:
            self.brews = [ Brew(session=session, data=brew_data) ]
     


    def tidy(self):

        # add required fields, if missing
        if not 'unit_type_id' in self.data:
            self.data['unit_type_id'] = UnitType.METRIC.value;
        if not 'recipe_type_id' in self.data:
            self.data['recipe_type_id'] = RecipeType.ALLGRAIN.value;

        # others
        if not 'source' in self.data:
            self.data['source'] = DEFAULT_SOURCE
        if not 'parent_recipe_id' in self.data:
            self.data['parent_recipe_id'] = None



    def toGal(self, value):

        if self.data['unit_type_id'] == UnitType.METRIC.value:
            return Util.lToGal(value)
        else:
            return value



    def toLb(self, value):

        if self.data['unit_type_id'] == UnitType.METRIC.value:
            return Util.kgToLb(value)
        else:
            return value



    def toOz(self, value):

        if self.data['unit_type_id'] == UnitType.METRIC.value:
            return Util.gToOz(value)
        else:
            return value



    def recalculate(self, force=False):

        """Recalculate those recipe attributes that are not primarily
        part of the recipe, but can be derived from other
        user-adjusted attributes of ingredients, mash steps, etc., and
        the equipment. Those attributes than can be recalculated but
        that hold already some value, are only recalculated, if the
        force flags is True."""

        ## most parts of these calculations are based on the
        ## javascript code from the Grainfather web frontend, so that
        ## our calculations match those after uploading recipes.

        attenuation = 0.75 # if we do not know any better
        if ("yeasts" in self.data) and (len(self.data["yeasts"]) > 0):
            attenuation = 0.0
            for yeast in self.data["yeasts"]:
                if ("attenuation" in yeast) and (yeast["attenuation"] > 0):
                    attenuation += float(yeast["attenuation"])
                else:
                    attenuation += 0.75  # if no explicit attenuation is given
            attenuation /= len(self.data["yeasts"])
        # TBD: take influence of maltose rest temperature into account

        postBoilVolume = self.toGal(self.data["batch_size"] + self.data["losses"])
        color = 0.0
        earlyGravityPoints = 0.0
        totalGravityPoints = 0.0

        if ("fermentables" in self.data) and (len(self.data["fermentables"]) > 0):
            for fermentable in self.data["fermentables"]:
                if fermentable["amount"] > 0:
                    if fermentable["fermentable_usage_type_id"] == FermentableUsageType.MASH.value:
                        efficiency = self.data["efficiency"]
                    elif fermentable["fermentable_usage_type_id"] == FermentableUsageType.STEEP.value:
                        efficiency = 0.5 # we assume this as a default steep efficiency
                    else:
                        efficiency = 1.0
                    g = self.toLb(fermentable["amount"]) * fermentable["ppg"] * efficiency / postBoilVolume
                    totalGravityPoints += g
                    if fermentable["fermentable_usage_type_id"] != FermentableUsageType.LATEADDITION.value:
                        earlyGravityPoints += g
                    color += self.toLb(fermentable["amount"]) * fermentable["lovibond"] / postBoilVolume
        else:
            totalGravityPoints = 0

        if (force) or (not "og" in self.data) or (self.data["og"] == None) or (float(self.data["og"]) <= 1.000):
            self.data["og"] = float("%.3f" % (1.0 + totalGravityPoints / 1000))
        if (force) or (not "fg" in self.data) or (self.data["fg"] == None) or (float(self.data["fg"]) <= 1.000):
            self.data["fg"] = float("%.3f" % (1.0 + (totalGravityPoints * (1.0 - attenuation)) / 1000))
        if (force) or (not "abv" in self.data) or (self.data["abv"] == None) or (float(self.data["abv"]) <= 0.0):
            self.data["abv"] = float("%.01f" % ((self.data["og"] - self.data["fg"]) * 131.25))
        if (force) or (not "srm" in self.data) or (self.data["srm"] == None) or (float(self.data["srm"]) <= 0.0):
            self.data["srm"] = float("%.1f" % (1.49 * math.pow(color, 0.69)))
        if (force) or (not "calories" in self.data) or (self.data["calories"] == None) or (float(self.data["calories"]) <= 0.0):
            self.data["calories"] = round(1881.22 * self.data["fg"] * (self.data["og"] - self.data["fg"]) / (1.775 - self.data["og"]) + 3550.0 * self.data["fg"] * (0.1808 * self.data["og"] + 0.8192 * self.data["fg"] - 1.0004))

        print("XXX attenuation:%s totalGravityPoints:%s postboil:%s og:%s" % (attenuation, totalGravityPoints, postBoilVolume, self.data["og"]))

        earlyOG = 1.0 + earlyGravityPoints / 1000
            
        if ("hops" in self.data) and (len(self.data["hops"]) > 0):
            totalIBU = 0.0
            for hop in self.data["hops"]:
                ibu = 0.0
                if hop["hop_usage_type_id"] in [HopUsageType.MASH.value, HopUsageType.FIRSTWORT.value, HopUsageType.BOIL.value, HopUsageType.AROMA.value]:
                    if hop["hop_usage_type_id"] == HopUsageType.FIRSTWORT.value:
                        time = self.data["boil_time"]
                    else:
                        time = hop["time"]
                    if hop["hop_usage_type_id"] in [HopUsageType.MASH.value, HopUsageType.FIRSTWORT.value, HopUsageType.BOIL.value]:
                        factor = 1.1
                    else:
                        factor = 1.0
                    utilization = 1.65 * math.pow(0.000125, earlyOG - 1.0) * (1.0 - math.exp(-0.04 * time)) / 4.15 * factor
                    ibu = hop["aa"] / 100.0 * self.toOz(hop["amount"]) * 7490 / postBoilVolume * utilization

                    if hop["hop_usage_type_id"] == HopUsageType.AROMA.value:
                        ibu /= 2
                    elif hop["hop_usage_type_id"] == HopUsageType.MASH.value:
                        ibu *= 0.2
                    elif hop["hop_usage_type_id"] == HopUsageType.FIRSTWORT.value:
                        ibu *= 1.1 # Note: other sources say that first worst hopping leads to slightly _less_ bitterness ?!
                    print("XXX earlyOG:%s postboil:%s aa:%s amount:%s factor:%s util:%s time:%s  -> ibu:%s" % (earlyOG, postBoilVolume, hop["aa"], hop["amount"], factor, utilization, time, ibu))
                    totalIBU += ibu
                if (force) or (not "ibu" in hop) or (hop["ibu"] == None):
                    hop["ibu"] = float("%0.01f" % ibu)
            if (force) or (not "ibu" in self.data) or (self.data["ibu"] == None):
                self.data["ibu"] = float("%0.01f" % totalIBU)

        if (force) or (not "bggu" in self.data) or (self.data["bggu"] == None) or (float(self.data["bggu"]) <= 0.0):
            if (self.data["og"] <= 1.0) and (self.data["ibu"]) > 0:
                self.data["bggu"] = 1.0
            elif (self.data["og"] == 0) and (self.data["ibu"]) == 0:
                self.data["bggu"] = 0.0
            else:
                self.data["bggu"] = self.data["ibu"] / ((self.data["og"] - 1.0) * 1000)



    def getBrews(self, full=False):

        if self.brews != None:

            return self.brews

        self.brews = []

        url = "https://brew.grainfather.com/recipes/{recipe_id}/brew-sessions/data?page=1".format(recipe_id=self.get("id"))

        while url:

            response = self.session.get(url)
            responsedata = json.loads(response.text)

            for data in responsedata["data"]:
                brew = Brew(data=data)
                self.session.register(brew)
                self.brews.append(brew)
                    
            if "next_page_url" in responsedata:
                url = responsedata["next_page_url"]
            else:
                break

        if full:
            for brew in self.brews:
                brew.reload()

        return self.brews



class Brew(Object):

    urlload = "https://brew.grainfather.com/recipes/{recipe_id}/brew-sessions/data/{id}"
    urlsave = "https://brew.grainfather.com/recipes/{recipe_id}/brew-sessions/{id}"
    urlcreate = "https://brew.grainfather.com/recipes/{recipe_id}/brew-sessions/"

    recipe_id = None



    def __init__(self, session=None, recipe=None, id=None, data=None):

        if recipe and recipe.get("id"):
            # fill in recipe_id into url templates
            self.recipe_id = recipe.get("id")
            self.urlload = self.urlload.format(recipe_id=self.recipe_id, id="{id}")
            self.urlsave = self.urlsave.format(recipe_id=self.recipe_id, id="{id}")
            self.urlcreate = self.urlcreate.format(recipe_id=self.recipe_id)

        super(Brew, self).__init__(session=session, id=id, data=data)

     


    def tidy(self):

        # add required fields, if missing
        if not 'unit_type_id' in self.data:
            self.data['unit_type_id'] = UnitType.METRIC.value;

        # others
        if not 'recipe_id' in self.data:
            self.data['recipe_id'] = None



class Fermentable(Object):

    # TBD... how can we access specific ingredients?

    urlload = "https://brew.grainfather.com/api/ingredients/fermentables?api_token={api_token}&q={id}"
    urlsave = None
    urlcreate = None



class Interpreter(object):

    kbh = None
    session = None
    logger = None


    def __init__(self, kbh=None, bs=None, session=None, config=None):

        self.kbh = kbh
        self.bs = bs
        self.session = session
        self.config = config

        self.logger = logging.getLogger('interpreter')



    def list(self, args):

        flagBrews = False
        flagSortNames = False
        flagSortDates = False

        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        try:
            opts, args = getopt.getopt(args, "vbnd", ["verbose", "brews", "name", "date"])
        except getopt.GetoptError as err:
            self.logger.error(str(err))
            return
        for o, a in opts:
            if o in ("-v", "--verbose"):
                flagBrews = True
            elif o in ("-b", "--brews"):
                flagBrews = True
            elif o in ("-n", "--name"):
                flagSortNames = True
            elif o in ("-d", "--date"):
                flagSortDates = True
            else:
                assert False, "unhandled option"

        # build a list of recipe names
        if len(args) >= 1:
            namepattern = args[0]
        else:
            namepattern = "*"

        gf_recipes = self.session.getMyRecipes(namepattern, brews=flagBrews)
        all_recipes = gf_recipes

        if self.kbh:
            kbh_recipes = self.kbh.getRecipes(namepattern)
            for recipe in kbh_recipes:
                if recipe.get("name") not in [r.get("name") for r in all_recipes]:
                    all_recipes.append(recipe)
        else:
            kbh_recipes = None

        # sort by the requested attribute
        if flagSortDates:
            all_recipes = sorted(all_recipes, key=lambda r: "%s:%s" % (r.get("updated_at")[:16],r.get("name")))
        else:
            all_recipes = sorted(all_recipes, key=lambda r: r.get("name"))

        # now print the lines
        firstLine = True
        for name in [r.get("name") for r in all_recipes]:

            if firstLine:
                print("%8s flags %16s %16s %7s %s" % ("ID", "KBH update", "GF update", "size", "name/attributes"))
                firstLine = False

            # try to find the GF and KBH representations of the current recipe name
            gf_recipe  = next((recipe for recipe in gf_recipes  if recipe.get("name") == name), None)
            if kbh_recipes:
                kbh_recipe = next((recipe for recipe in kbh_recipes if recipe.get("name") == name), None)
            else:
                kbh_recipe = None

            recipe = gf_recipe if gf_recipe else kbh_recipe

            print("%8s r%s%s%s%s %16s %16s %7s %s" %
                  (gf_recipe.get("id") if gf_recipe else "-",
                   "k" if kbh_recipe else "-",
                   "g" if gf_recipe else "-",
                   "p" if gf_recipe and gf_recipe.get("is_public") else "-",
                   "o" if gf_recipe and kbh_recipe and kbh_recipe.get("updated_at") > gf_recipe.get("updated_at") else "-",
                   Util.utcToLocal(kbh_recipe.get("updated_at"))[:16] if kbh_recipe else "-",
                   Util.utcToLocal(gf_recipe.get("updated_at"))[:16] if gf_recipe else "-",
                   "%.1f" % (recipe.get("batch_size")) + "l" if recipe.get("unit_type_id") == 10 else "gal",
                   name))
            
            if flagBrews:

                # KBH has a representation of exactly one brew per recipe
                # TBD...
                kbh_brew = None

                if gf_recipe:

                    gf_brews = gf_recipe.brews

                    # TBD: sort (by date, newest last)
                    gf_brews = sorted(gf_brews, key=lambda b: b.get("updated_at"))

                    if len(gf_brews) > 0:
                        brews = gf_brews
                        # ...and assume the kbh_brew corresponds with the last (newest) gf_brew
                    else:
                        brews = []
                        if kbh_brew:
                            brews.append(kbh_brew)

                    for brew in brews:

                        if brew == brews[-1]:
                            latest = True
                        else:
                            latest = False

                        attrs = []
                        attrs.append(BrewStatusType.getName(brew.get("status")))
                        attrs = str(attrs)

                        # TBD
                        volume = brew.get("boil_volume_est")

                        print("%8s b%s%s%s%s %16s %16s %7s %s" %
                              (brew.get("id") if brew.get("id") else "-",
                               "k" if kbh_brew and (latest == True) else "-",
                               "g" if len(gf_brews) > 0 else "-",
                               "p" if brew.get("is_public") else "-",
                               "o" if kbh_brew and (latest == True) and len(gf_brews) > 0 and kbh_brew.get("updated_at") > brew.get("updated_at") else "-",
                               Util.utcToLocal(kbh_brew.get("updated_at"))[:16] if kbh_brew and (latest == True) and len(gf_brews) > 0 else "-",
                               Util.utcToLocal(brew.get("updated_at"))[:16] if len(gf_brews) > 0 else "-",
                               "%.1f" % (volume) + "l" if brew.get("unit_type_id") == 10 else "gal",
                               attrs))



    def dump(self, args):

        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if len(args) >= 1:
            namepattern = args[0]
        else:
            namepattern = "*"

        recipes = self.session.getMyRecipes(namepattern, full=True)

        for recipe in recipes:
            
            recipe.print()



    def push(self, args):
        
        if not self.kbh:
            self.logger.error("No KBH database, use -k option")
            return
            
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if len(args) >= 1:
            namepattern = args[0]
        else:
            namepattern = "*"

        kbh_recipes = self.kbh.getRecipes(namepattern)
        if len(kbh_recipes) == 0:
            return

        # we have to know all our recipes on the GF server so that
        # we can decide which recipe to create and which to update
        gf_recipes = self.session.getMyRecipes()

        for kbh_recipe in kbh_recipes:
            
            # try to find matching GF recipe
            id = None
            for gf_recipe in gf_recipes:
                if gf_recipe.get("name") == kbh_recipe.get("name"):
                    id = gf_recipe.get("id")
                    break
            if id:
                if (gf_recipe.get("updated_at") > kbh_recipe.get("updated_at")) and (not self.session.force):
                    self.logger.info("%s needs no update" % gf_recipe)
                    self.logger.debug("kbh:%s, gf:%s" % (kbh_recipe.get("updated_at"), gf_recipe.get("updated_at")))
                else:
                    self.session.register(kbh_recipe, id=id)
                    self.logger.info("Updating %s" % gf_recipe)
                    self.logger.debug("kbh:%s, gf:%s" % (kbh_recipe.get("updated_at"), gf_recipe.get("updated_at")))
                    kbh_recipe.save()
            else:
                self.logger.info("Creating %s" % kbh_recipe)
                self.session.register(kbh_recipe)
                kbh_recipe.save()
            


    def delete(self, args):
        
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if len(args) >= 1:
            namepattern = args[0]
        else:
            self.logger.error("No name pattern supplied")
            return

        recipes = self.session.getMyRecipes(namepattern)

        for recipe in recipes:
            
            recipe.delete()
            


    def diff(self, args):

        if not self.kbh:
            self.logger.error("No KBH database, use -k option")
            return
            
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if len(args) >= 1:
            namepattern = args[0]
        else:
            self.logger.error("No name supplied")
            return

        kbh_recipe = self.kbh.getRecipe(namepattern=namepattern)
        gf_recipe = self.session.getMyRecipe(namepattern=namepattern)

        if kbh_recipe and gf_recipe:
        
            kbh_file = tempfile.NamedTemporaryFile(delete=False)
            kbh_file.write(str.encode(json.dumps(kbh_recipe.data, sort_keys=True, indent=4)))
            kbh_file.flush()
            kbh_file.seek(0)

            gf_file = tempfile.NamedTemporaryFile(delete=False)
            gf_file.write(str.encode(json.dumps(gf_recipe.data, sort_keys=True, indent=4)))
            gf_file.flush()
            gf_file.seek(0)

            subprocess.call(['diff', '-u', kbh_file.name, gf_file.name])

            kbh_file.close()
            gf_file.close()
            os.unlink(kbh_file.name)
            os.unlink(gf_file.name)



    def daemon(self, args):

        if not self.kbh:
            self.logger.error("No KBH database, use -k option")
            return
            
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        self.push(args)

        self.logger.info("Now watching %s for changes..." % (self.config["kbhFile"]))
        mtime = None
        while True:
            stat = os.stat(os.path.expanduser(self.config["kbhFile"]))
            if mtime and (stat.st_mtime != mtime):
                time.sleep(1)
                self.logger.info("Detected KBH change, syncing...")
                self.kbh.reopen()
                self.push(args)
            mtime = stat.st_mtime
            time.sleep(1)



    def logout(self, args):

        self.session.logout()



    def test(self, args):

        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if len(args) >= 1:
            namepattern = args[0]
        else:
            namepattern = "*"

        bs_recipes = self.bs.getRecipes(namepattern=namepattern)
        self.logger.info("found %d BS recipes" % len(bs_recipes))
#        if len(bs_recipes) == 0:
#            return

        gf_recipes = self.session.getMyRecipes(namepattern=namepattern)
        self.logger.info("found %d GF recipes" % len(gf_recipes))

        kbh_recipes = self.kbh.getRecipes(namepattern=namepattern)
        self.logger.info("found %d KBH recipes" % len(kbh_recipes))

        for bs_recipe in bs_recipes:

            # try to find matching GF recipe
            id = None
            for gf_recipe in gf_recipes:
                if gf_recipe.get("name") == bs_recipe.get("name"):
                    id = gf_recipe.get("id")
                    break
                
            print(json.dumps(bs_recipe.data, sort_keys=True, indent=4))

            if id:
                if ((gf_recipe.get("updated_at")[:10] + "T00:00:00.000000Z") > bs_recipe.get("updated_at")) and (not self.session.force):
                    self.logger.info("%s needs no update" % gf_recipe)
                    self.logger.debug("bs:%s, gf:%s" % (bs_recipe.get("updated_at"), gf_recipe.get("updated_at")))
                else:
                    self.session.register(bs_recipe, id=id)
                    self.logger.info("Updating %s" % gf_recipe)
                    self.logger.debug("bs:%s, gf:%s" % (bs_recipe.get("updated_at"), gf_recipe.get("updated_at")))
                    bs_recipe.save()
            else:
                self.logger.info("Creating %s" % bs_recipe)
                self.session.register(bs_recipe)
                bs_recipe.save()

#        print(json.dumps(r.data, sort_keys=True, indent=4))
#        r.recalculate(force=True)
#        print(json.dumps(r.data, sort_keys=True, indent=4))



def usage():
    print("""Usage: %s [options] [command [argument] ]
  -v           --verbose             increase the logging level
  -d           --debug               run at maximum debug level
  -s           --syslog              send logging to syslog
  -n           --dryrun              do not write any data
  -f           --force               force operations
  -h           --help                this help message
  -c file      --config file         read configuration file
  -u username  --user username       Grainfather community username
  -p password  --password password   Grainfather community password
  -P file      --pwfile file         read password from file
  -l           --logout              logout (instead of keeping session persistent)
  -k file      --kbhfile file        Kleiner Brauhelfer database file
  -b file      --bsdir dir           BeerSmith3 database directory
Commands:
  list ["namepattern"]               list user's recipes
  dump ["namepattern"]               dump user's recipes 
  push ["namepattern"]               push recipes from KBH to GF
  delete "namepattern"               delete user's recipes
  diff "namepattern"                 show json diff between kbh and gf version of a recipe
  daemon                             run as daemon keeping GF synced with KBH
  logout                             logout and invalidate persistent session""" % sys.argv[0])


def mergeConfig(config, filename, notify=True):

    try:
        with open(os.path.expanduser(filename)) as f:
            data = json.load(f)
            config = {**config, **data}
    except Exception as error:
        if notify or (errno.errorcode[error.errno] != "ENOENT"):
            logging.getLogger().warn("Could not read configuration from %s: %s" % (filename, error))
    
    return config



def main():

    level = None
    session = None
    kbh = None
    bs = None
    dryrun = False
    force = False
    logout = False

    logging.basicConfig()
    level = logging.WARNING
    logger = logging.getLogger()

    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.WARN)

    config = dict(
        globalConfigFile = "/ibr/local/etc/grainfather.config",
        configFile = "~/.grainfather.config",
        passwordFile = "~/.grainfather.password",
        stateFile = "~/.grainfather.state",
        username = None,
        password = None,
        kbhFile = "~/.kleiner-brauhelfer/kb_daten.sqlite",
        bsDir = "~/Documents/BeerSmith3",
        bsPattern = "Sync"
        )
    
    config = mergeConfig(config, config["globalConfigFile"], notify=False)
    config = mergeConfig(config, config["configFile"], notify=False)

    try:
        opts, args = getopt.getopt(sys.argv[1:],
                                   "vdqsnfhc:u:p:P:lk:b:",
                                   ["verbose", "debug", "quiet", "syslog", "dryrun", "force", "help", "config=", "user=", "password=", "pwfile=", "logout", "kbhfile=", "bsdir="])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    for o, a in opts:

        if o in ("-v", "--verbose"):
            if level == logging.WARNING:
                level = logging.INFO
                logger.setLevel(level)
            elif level == logging.INFO:
                level = logging.DEBUG
                logger.setLevel(level)
            else:
                requests_log.setLevel(level)
                requests_log.propagate = True

        elif o in ("-d", "--debug"):
            level = logging.DEBUG
            logger.setLevel(level)
            requests_log.setLevel(level)
            requests_log.propagate = True
            http.client.HTTPConnection.debuglevel = 1

        elif o in ("-s", "--syslog"):
            logger.handlers = []
            handler = logging.handlers.SysLogHandler(address = "/dev/log",
                                                     facility = logging.handlers.SysLogHandler.LOG_DAEMON)
            handler.ident = "Grainfather[%d]: " % (os.getpid())
            logger.addHandler(handler)

        elif o in ("-q", "--quiet"):
            logger.handlers = []

        elif o in ("-n", "--dryrun"):
            dryrun = True

        elif o in ("-f", "--force"):
            force = True

        elif o in ("-h", "--help"):
            usage()
            sys.exit()

        elif o in ("-c", "--config"):
            config = mergeConfig(config, a, notify=True)

        elif o in ("-u", "--user"):
            config["username"] = a

        elif o in ("-p", "--password"):
            config["password"] = a

        elif o in ("-P", "--pwfile"):
            config["passwordFile"] = a

        elif o in ("-l", "--logout"):
            logout = True

        elif o in ("-k", "--kbhfile"):
            config["kbhFile"] = a

        elif o in ("-b", "--bsdir"):
            config["bsDir"] = a

        else:
            assert False, "unhandled option"

    if "passwordFile" in config:
        try:
            with open(os.path.expanduser(config["passwordFile"])) as f:
                password = f.readline()
                config["password"] = password.rstrip('\r\n')
        except Exception as error:
            logger.error("Could not read password from file: %s" % (error))

    session = Session(username=config["username"], password=config["password"],
                      readonly=dryrun, force=force, stateFile=config["stateFile"])

    if (config["kbhFile"]):
        kbh = KleinerBrauhelfer(os.path.expanduser(config["kbhFile"]))

    if (config["bsDir"]):
        bs = BeerSmith3(dir=os.path.expanduser(config["bsDir"]), pattern=config["bsPattern"])

    interpreter = Interpreter(kbh=kbh, bs=bs, session=session, config=config)

    op = None
    arg = None
    if len(args) >= 1:
        op = args[0]
        result = getattr(interpreter, op)(args[1:])

    if logout:
        session.logout()



if __name__ == '__main__':
    sys.exit(main())

