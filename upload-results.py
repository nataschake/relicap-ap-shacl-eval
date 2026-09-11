import os
import sys
import urllib
import requests
from rdflib import Graph, Namespace, Literal, XSD
from rdflib.plugins.parsers.notation3 import BadSyntax

DATA_DIR = '.'
FN_VAL = 'validation-report.ttl'
FN_TIM = 'timing.txt'
EX = Namespace("http://example.org/ns#")
GDBURL = "https://cim.ontotext.com/graphdb/"
GDBREPO = "cim-shacl"
GDBCONTEXT = "<https://github.com/entsoe/application-profiles/SHACL/reports>"
GDBUSER = ""  # Replace with your username if needed
GDBPASS = ""# Replace with your password if needed

class GraphDBUploader:
    def __init__(self, data_dir):
        """
        Initialize the GraphDBUploader.

        Args:
            data_dir (str): Directory containing validation and timing files.
        """
        self.auth_header = ""  # Stores the Authorization header for GraphDB
        self.clean_graph = True  # Whether to clean the target graph before upload
        self.data_dir = data_dir  # Path to the directory with validation data

    def upload_validation_results(self):
        """
        Upload validation results from subdirectories in the data directory.
        Processes each subdirectory to extract and upload validation data.
        """
        with os.scandir(self.data_dir) as entries:
            for entry in entries:
                if entry.is_dir():
                    print(f"Processing reports in: {entry.name}")
                    try:
                        # Construct file paths for validation and timing files
                        validation_file = os.path.join(entry.path, FN_VAL)
                        timing_file = os.path.join(entry.path, FN_TIM)

                        # Check if both files exist
                        if os.path.isfile(validation_file) and os.path.isfile(timing_file):
                            # Read and decode validation file (Turtle format)
                            with open(validation_file, 'rb') as f:
                                content = f.read()
                                text = content.decode('utf-8', errors='replace')
                                g = Graph()
                                g.parse(data=text, format="turtle")  # Parse Turtle data

                            # Parse metadata from timing file
                            metadata = self.parse_metadata(timing_file)

                            # Append metadata to the graph and upload
                            g = self.append_metadata(g, metadata)
                            self.post_to_endpoint(g)

                    except BadSyntax as bs:
                        print(f"A syntax error occurred: {bs}")
                    except Exception as e:
                        print(f"A non-syntax error occurred: {e}")

    def parse_metadata(self, file_path):
        """
        Parse metadata from a timing file (key-value pairs separated by colons).

        Args:
            file_path (str): Path to the timing file.

        Returns:
            dict: Dictionary of metadata key-value pairs.
        """
        metadata = {}
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line and ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
        return metadata

    def get_cleaned_val_report_graph(self, graph):
        """
        Clean and filter validation report triples using a SPARQL query.

        Args:
            graph (Graph): Input graph containing validation data.

        Returns:
            Graph: Filtered graph with valid triples.
        """
        # SPARQL query to extract valid triples, excluding rdf4j:nil
        query = """
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            PREFIX rdf4j: <http://rdf4j.org/schema/rdf4j#>
            SELECT *
            WHERE {
                ?s a sh:ValidationReport .
                ?s ?p ?o .
                OPTIONAL {?o ?pp ?oo .}
                MINUS {?o ?pp rdf4j:nil .}
            }
        """
        results = graph.query(query)
        result_graph = Graph()

        # Add filtered triples to the result graph
        for row in results:
            if not (row.s is None and row.p is None and row.o is None):
                result_graph.add((row.s, row.p, row.o))
            if not (row.pp is None and row.oo is None):
                result_graph.add((row.o, row.pp, row.oo))

        return result_graph

    def append_metadata(self, graph, metadata):
        """
        Add metadata as triples to the graph using a specific subject.

        Args:
            graph (Graph): Input graph to append metadata to.
            metadata (dict): Dictionary of metadata key-value pairs.

        Returns:
            Graph: Graph with appended metadata.
        """
        # Clean the validation report graph
        result_graph = self.get_cleaned_val_report_graph(graph)

        # Bind a namespace for the metadata predicates
        result_graph.bind("ex", EX)

        # Get the first subject from the graph (used as the common subject)
        subjects = list(graph.subjects())
        first_subject = subjects[0] if subjects else None

        if first_subject:
            # Add each metadata key-value pair as a triple
            for key, value in metadata.items():
                if key == "finished_at":
                    predicate = EX[self.transform_predicate(key)]
                    obj = Literal(value, datatype=XSD.dateTime)
                elif key == "duration_seconds":
                    predicate = EX[self.transform_predicate(key)]
                    obj = Literal(value, datatype=XSD.decimal)
                elif key == "http_status":
                    predicate = EX[self.transform_predicate(key)]
                    obj = Literal(value, datatype=XSD.integer)
                else:
                    predicate = EX[key]
                    obj = Literal(value)
                result_graph.add((first_subject, predicate, obj))

        return result_graph

    def transform_predicate(self, name):
        """
        Convert a key (e.g., "finished_at") to a predicate name (e.g., "finishedAt").

        Args:
            name (str): Key to transform.

        Returns:
            str: Transformed predicate name.
        """
        # Split the key by underscores and capitalize subsequent parts
        parts = name.split('_')
        return parts[0] + ''.join(part.capitalize() for part in parts[1:])

    def get_auth_header(self):
        """
        Retrieve and store the Authorization header for GraphDB authentication.

        Returns:
            str: Authorization header (Bearer token).
        """
        if self.auth_header == "":
            auth_url = f"{GDBURL}rest/login/{GDBUSER}"
            headers = {
                "X-GraphDB-Password": GDBPASS  # Authentication header
            }
            response = requests.post(auth_url, headers=headers)

            if response.status_code == 200:
                # Extract the Authorization header from the response
                self.auth_header = response.headers.get("Authorization")

        return self.auth_header

    def post_to_endpoint(self, g):
        """
        Post the graph to the GraphDB SPARQL endpoint.

        Args:
            g (Graph): Graph to upload.

        Returns:
            Response: HTTP response from the endpoint.
        """
        if self.clean_graph:
            self.drop_target_graph()  # Clean the target graph before upload

        # Serialize the graph in N-Triples format
        triples_data = g.serialize(format="ntriples")

        # Construct the SPARQL endpoint URL
        sparql_endpoint = f"{GDBURL}repositories/{GDBREPO}/statements?" + \
                          urllib.parse.urlencode({"context": GDBCONTEXT})

        # Set headers for the request
        headers = {
            "Content-Type": "application/n-triples",
            "Authorization": self.get_auth_header()
        }

        # Send the POST request
        response = requests.post(sparql_endpoint, data=triples_data, headers=headers)
        return response

    def drop_target_graph(self):
        """
        Drop the target graph in GraphDB using a SPARQL UPDATE query.

        Returns:
            Response: HTTP response from the endpoint.
        """
        # SPARQL UPDATE query to drop the named graph
        update = f'DROP GRAPH {GDBCONTEXT}'
        sparql_endpoint = f"{GDBURL}repositories/{GDBREPO}/statements"
        headers = {
            "Content-Type": "application/sparql-update",
            "Authorization": self.get_auth_header()
        }

        # Send the DROP GRAPH query
        response = requests.post(sparql_endpoint, data=update, headers=headers)
        self.clean_graph = False  # Prevent multiple cleanups
        return response


def main():
    """
    Main entry point for the script.
    Initializes the GraphDBUploader and starts the upload process.
    """
    uploader = GraphDBUploader(DATA_DIR)
    uploader.upload_validation_results()


if __name__ == "__main__":
    sys.exit(main())