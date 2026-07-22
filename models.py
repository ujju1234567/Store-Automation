from pydantic import BaseModel, Field
from typing import Optional

class DocumentExtraction(BaseModel):
    supplier_name: Optional[str] = Field(None, description="Name of the supplier or vendor.")
    supplier_address: Optional[str] = Field(None, description="Address of the supplier.")
    po_number: Optional[str] = Field(None, description="Purchase Order Number.")
    part_number: Optional[str] = Field(None, description="Part Number.")
    material_grade: Optional[str] = Field(None, description="Material Grade.")
    material_specification: Optional[str] = Field(None, description="Material Specification.")
    quantity: Optional[str] = Field(None, description="Quantity.")
    heat_number: Optional[str] = Field(None, description="Heat Number or Cast Number.")
    lot_number: Optional[str] = Field(None, description="Lot Number.")
    certificate_number: Optional[str] = Field(None, description="Certificate Number (CoC, MTC).")
    drawing_number: Optional[str] = Field(None, description="Drawing Number.")
    revision: Optional[str] = Field(None, description="Revision number or code.")
    issue_date: Optional[str] = Field(None, description="Issue Date of the document.")
    delivery_number: Optional[str] = Field(None, description="Delivery Challan Number or Delivery Reference.")
    invoice_number: Optional[str] = Field(None, description="Invoice Number.")
    customer_name: Optional[str] = Field(None, description="Customer Name.")
    status: Optional[str] = Field(None, description="Status (if mentioned).")
    remarks: Optional[str] = Field(None, description="Any remarks or additional notes.")
